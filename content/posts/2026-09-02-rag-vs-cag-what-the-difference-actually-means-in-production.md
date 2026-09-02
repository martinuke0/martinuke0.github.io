---
title: "RAG vs CAG: What the Difference Actually Means in Production"
date: "2026-09-02T21:13:00.792"
draft: false
tags: ["rag", "cag", "llm", "retrieval-augmented-generation", "ai-architecture", "vector-search"]
description: "RAG vs CAG explained: how cache-augmented generation differs from retrieval-augmented generation, when each wins, and how to design production LLM systems around them."
summary: "A practical, architecture-first comparison of Retrieval-Augmented Generation and Cache-Augmented Generation, with patterns for combining both in production LLM systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-rag-vs-cag-what-the-difference-actually-means-in-production.svg"
  alt: "Diagram-style illustration contrasting retrieval and cache flows feeding into an LLM."
  caption: ""
  relative: false
---

> **TL;DR** — RAG fetches fresh knowledge from a vector store or search index at query time, while CAG preloads long, stable context directly into the model's prompt window. RAG wins for freshness and scale; CAG wins for latency, determinism, and cost on bounded corpora. Most production systems end up combining both.

## What the Acronyms Actually Stand For

For two letters that get thrown around constantly, **RAG** and **CAG** are surprisingly easy to confuse. They both sit in front of the same thing — a large language model — and they both exist to solve the same root problem: language models don't know what they don't know, and they hallucinate when asked anyway.

**Retrieval-Augmented Generation (RAG)** is the older, more established pattern. At inference, the system takes the user's question, embeds it, runs a similarity search against an external knowledge base, fetches the top *k* chunks, stuffs them into the prompt, and lets the LLM answer. The retrieval happens per query. Knowledge is "out there," in a vector database like [pgvector](https://github.com/pgvector/pgvector), Pinecone, or Weaviate.

**Cache-Augmented Generation (CAG)** flips the assumption. Instead of retrieving at query time, you take a bounded corpus — say, a 200-page product manual or the rules of a board game — and you preload the entire thing into the model's context window once, or per session. The "cache" is the context itself. There is no vector DB call on the hot path.

The distinction is small in a diagram and enormous in production.

## Why the Pattern Matters

Both patterns are responses to the same failure: an LLM that confidently makes things up because the answer wasn't in its training data. But they attack the failure from opposite directions.

- **RAG** says: "Knowledge is too big to fit in a context window. Fetch the relevant slice at query time."
- **CAG** says: "Knowledge is bounded. Just load the whole thing into the window and skip the lookup."

Each makes a tradeoff. RAG accepts latency, infrastructure, and retrieval-quality risk in exchange for unbounded knowledge. CAG accepts that the corpus must fit (and stay fitting) in exchange for sub-100ms overhead and zero retrieval failures.

## How RAG Works in Practice

The canonical RAG pipeline is well-trodden. A user query arrives, gets embedded by the same model that built your index, and is sent to a vector store. The store returns the top *k* nearest neighbors by cosine or inner-product similarity. Those chunks, plus a system prompt and the user's question, are assembled into one prompt and sent to the LLM.

```python
from openai import OpenAI
from qdrant_client import QdrantClient

client = OpenAI()
qdrant = QdrantClient(host="localhost", port=6333)

def retrieve(question: str, collection: str = "docs", k: int = 5) -> str:
    query_embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=question,
    ).data[0].embedding

    hits = qdrant.search(
        collection_name=collection,
        query_vector=query_embedding,
        limit=k,
    )
    return "\n\n".join(h.point.payload["text"] for h in hits)

def answer(question: str) -> str:
    context = retrieve(question)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Answer using only the provided context."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
    )
    return response.choices[0].message.content
```

Three things make RAG production-grade but also production-fragile:

1. **Embedding quality.** If your chunker splits mid-thought and your embedder was trained on web text, your retrieval will miss. The blast radius of bad embeddings is silent and total.
2. **Index freshness.** A vector index is a snapshot. Stale documents return confidently wrong answers. Teams that skip the ingestion pipeline pay for it later.
3. **Prompt bloat.** Twenty retrieved chunks at 1,000 tokens each is 20,000 tokens of context before the user has typed a word. Costs balloon, latency creeps up, and attention dilution kicks in.

## How CAG Works in Practice

CAG is, structurally, much simpler. There is no vector store on the critical path. There is no embedding call. There is only the corpus and the model.

```python
from openai import OpenAI

client = OpenAI()

# Pretend this was loaded once from disk or a database.
CORPUS = open("product_manual.txt").read()

SYSTEM_PROMPT = f"""
You are a support agent for Acme Widget. Answer questions
strictly from the manual below. If the answer is not in the
manual, say "I don't know."

<manual>
{CORPUS}
</manual>
"""

def answer(question: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    )
    return response.choices[0].message.content
```

That's the whole pattern. In practice, CAG has three real flavors:

- **Static CAG.** The corpus is baked into the system prompt and shipped as part of the deployment. Changing the manual means redeploying.
- **Session CAG.** The corpus is loaded into the conversation history on the first turn of a session and stays there. Useful for long-running agents that need a stable frame of reference.
- **Dynamic CAG.** A pre-fetched, pre-summarized bundle of context is built per user or per route and passed in via the system prompt. This is the production-friendly form.

The appeal is obvious: **no vector DB, no embedding model, no retrieval failure mode.** The ceiling is the context window.

## The Hard Comparison

Once you stop looking at architecture diagrams and start looking at latency budgets, the differences sharpen fast.

### Latency

A RAG query pays three costs: an embedding call (~50–150ms), a vector search (~5–30ms for a warm index), and an LLM call that itself is slower because the prompt is bigger. End-to-end, that's often 600ms to 2 seconds before any network jitter.

A CAG query pays one cost: the LLM call. With modern providers and prompt caching (Anthropic and OpenAI both cache repeated system prompts at the server), you can hit 200–500ms consistently, and sub-200ms once the cache is warm.

For interactive UI — chat overlays, IDE helpers, voice agents — that 1–2 second difference is the difference between "feels instant" and "feels like a chatbot."

### Cost

RAG token economics are brutal in production. You pay for the embedding call per query, the LLM input tokens for retrieved context, and the LLM output tokens. A mid-traffic app doing 10 million queries a month can easily burn six figures on retrieval-augmented prompts.

CAG shifts the cost curve. The system prompt is the same on every request. With [Anthropic's prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) or [OpenAI's cached prompts](https://platform.openai.com/docs/guides/prompt-caching), you pay full price once and ~10% of the price for every subsequent call within the cache TTL. For high QPS against a stable corpus, CAG is dramatically cheaper.

### Freshness

This is where CAG loses, and it's the reason RAG exists.

CAG is bounded by what fits in the window, and stale the moment the corpus changes. If your product catalog updates hourly, CAG either can't help you or requires a redeploy per hour, which defeats the purpose.

RAG re-indexes incrementally. New documentation, corrected answers, fresh pricing — they're queryable within minutes of landing in the database. For anything time-sensitive, RAG wins by default.

### Failure Modes

Every architecture has a way to be wrong. RAG's are well-documented:

- **Retrieval miss.** The right answer is in the corpus but the embedding didn't find it.
- **Hallucinated citation.** The LLM cites a chunk that exists but doesn't say what the LLM claims it says.
- **Index drift.** The vector store and the source of truth disagree because of a botched ingestion job.

CAG's failure modes are different and, often, easier:

- **Truncation.** The corpus is bigger than the window and silently gets cut. The model doesn't know it's missing half the manual.
- **Out-of-corpus hallucination.** Ask CAG about a topic that isn't in the manual and it'll sometimes invent an answer anyway, despite the system prompt.
- **Static rot.** The manual goes stale. The model continues to answer with full confidence.

The point isn't that one set of failures is "better." It's that they require different mitigation strategies.

## Patterns in Production

The most interesting systems I've seen don't pick a side. They layer.

### CAG for the Bounded Frame, RAG for the Tail

A common pattern in enterprise SaaS: the product docs, the support runbooks, and the policy documents fit in CAG. They're stable, they're bounded, and 80% of user questions live in them. The remaining 20% — account-specific questions, billing edge cases, recent incidents — are answered by RAG over a transactional database.

The system prompt carries the CAG corpus. The RAG retrieval happens only when a classifier decides the question is out-of-frame. End-to-end latency stays low for the common case; freshness stays high for the long tail.

### CAG as a Pre-Retrieval Filter

Inverse pattern: RAG runs first, but CAG holds a small, stable "ground truth" set — regulatory text, contract clauses, style guidelines — that should always be in the prompt regardless of what the user asked. Retrieval adds the variable, query-specific context on top.

This is how a lot of legal-tech and compliance tools work. The compliance text is CAG. The case-specific facts are RAG.

### CAG with RAG-Backed Invalidation

You serve CAG for performance, but a background job monitors the corpus. When the source-of-truth changes, you invalidate the prompt cache and trigger a refresh. The hot path stays CAG-fast; correctness stays RAG-fresh.

This is the same shape as a CDN with origin pull. Treat the context window like an edge cache and the vector store like the origin.

## When to Choose Which

A short decision rule, tuned for engineering teams shipping this quarter:

| Situation | Pick | Why |
|---|---|---|
| Corpus is bounded and changes rarely | **CAG** | Latency, cost, determinism |
| Corpus is large or changes often | **RAG** | Freshness, scale |
| Strict latency budget (<300ms p50) | **CAG** | No retrieval hop |
| Need to cite sources to users | **RAG** | Citations are real, retrievable chunks |
| Hallucination risk must be auditable | **RAG** | You can inspect what was retrieved |
| Long-running agent with stable role | **CAG** | Whole "world" fits in context |
| Personalization per user | **RAG** | CAG would need a unique prompt per user |

Most teams that think they need RAG actually need CAG for 70% of their traffic and RAG for the rest. Most teams that think they need CAG are about to hit a corpus that grew past the window and weren't ready for it.

## Architectural Considerations

A few things worth knowing if you're designing either system for real:

- **Chunking strategy is the soul of RAG.** Bad chunks doom good embeddings. For technical docs, semantic chunking at heading boundaries beats fixed-size windows almost every time. The [LangChain text splitters docs](https://python.langchain.com/docs/how_to/text_splitters/) are a reasonable starting point, even if you don't use the framework.
- **Hybrid search beats pure vector search.** Combining BM25 keyword search with dense retrieval — what [Weaviate calls hybrid search](https://weaviate.io/developers/weaviate/search/hybrid) — dramatically improves recall on rare terms, product SKUs, and proper nouns.
- **Prompt caching is the unglamorous win.** If you're running CAG, make sure your provider supports cached system prompts and that you're structuring the prompt so the stable prefix is exactly that — stable. A single timestamp in the system prompt will defeat the cache.
- **Evaluate, don't guess.** Tools like [Ragas](https://docs.ragas.io/) for RAG and simple held-out test sets for CAG will tell you which pattern is actually working. The intuition is usually wrong.
- **Window size changes the answer.** When GPT-3.5 came out, CAG was a joke — 4K tokens wasn't enough for anything interesting. With 128K and 200K context windows now standard, CAG is a real option for an entire new class of problems.

## Key Takeaways

- **RAG and CAG solve the same problem from opposite directions.** RAG fetches per query; CAG preloads per session or per deployment.
- **Latency and cost favor CAG** — often by an order of magnitude — when the corpus fits.
- **Freshness and scale favor RAG**, especially when the corpus is large, fast-moving, or personalized.
- **Citations and auditability favor RAG.** You can show the user exactly which chunk the answer came from.
- **The right answer in production is usually "both."** CAG for the bounded, stable, hot-path knowledge; RAG for the long tail and the freshness.
- **Treat the context window like a cache.** Use prompt caching, version it, and design invalidation flows. CAG is fast precisely *because* it's a cache.
- **Evaluate relentlessly.** Whichever pattern you pick, the metric that matters is grounded answer quality on real user questions, not benchmark scores.

## Further Reading

- [Retrieval-Augmented Generation for Large Language Models: A Survey](https://arxiv.org/abs/2312.10997) — the canonical survey covering RAG architectures, challenges, and variants.
- [Anthropic Prompt Caching Documentation](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) — the mechanism that makes CAG economically viable at scale.
- [OpenAI Prompt Caching Guide](https://platform.openai.com/docs/guides/prompt-caching) — same idea, different provider, useful for cost modeling.
- [pgvector: Open-source vector search for Postgres](https://github.com/pgvector/pgvector) — the practical choice for RAG when you already run Postgres.
- [Ragas: Evaluation framework for RAG pipelines](https://docs.ragas.io/) — the most accessible tool for measuring whether your retrieval is actually helping.
- [Weaviate Hybrid Search](https://weaviate.io/developers/weaviate/search/hybrid) — a clear write-up of why BM25 + dense vectors beats either alone.