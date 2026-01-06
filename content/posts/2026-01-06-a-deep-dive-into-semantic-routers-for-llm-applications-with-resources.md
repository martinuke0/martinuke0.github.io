---
title: "A Deep Dive into Semantic Routers for LLM Applications (With Resources)"
date: "2026-01-06T08:50:03.390"
draft: false
tags: ["semantic-routing", "llm", "ai-engineering", "vector-search", "agents"]
---

## Introduction

As language models are woven into more complex systems—multi-tool agents, retrieval-augmented generation, multi-model stacks—**“what should handle this request?”** becomes a first-class problem.

That’s what a **semantic router** solves.

Instead of routing based on keywords or simple rules, a semantic router uses **meaning** (embeddings, similarity, sometimes LLMs themselves) to decide:

- Which **tool**, **model**, or **chain** to call  
- Which **knowledge base** to query  
- Which **specialized agent** or **microservice** should own the request  

This post is a **detailed, practical guide** to semantic routers:

- What they are and why they matter  
- Core building blocks (embeddings, vector search, route specs, policies)  
- How to design and implement your own semantic router  
- Advanced patterns (hierarchical routing, cost-aware routing, hybrid rule/semantic routing)  
- How to evaluate and debug routing decisions  
- Libraries and resources to go deeper (with links)

---

## 1. What Is a Semantic Router?

A **semantic router** is a component that uses semantic similarity or LLM reasoning to map an input (usually text) to one of many possible **destinations**:

- A specific **LLM** (e.g., GPT-4 vs small open-source model)  
- A **tool** (calculator, database query, search API, code executor…)  
- A **workflow/chain** (RAG vs pure generation vs translation vs classification)  
- A **domain-specific agent** (billing support vs technical support vs sales)  

### 1.1 Traditional routing vs semantic routing

**Traditional (syntactic) routing:**

- Regex rules  
- Keyword-based intents (“if text contains ‘refund’ → refund flow”)  
- Static decision trees  

Limitations:

- Brittle to wording changes  
- Struggles with nuanced intents (“I can’t log in” vs “How do I reset my password?”)  
- Hard to maintain at scale (dozens/hundreds of tools/agents)

**Semantic routing:**

- Uses **embeddings** (vector representations) or direct LLM classification  
- Compares user input with **route descriptions** or **example queries**  
- Can generalize to unseen phrasing and synonyms  

Benefits:

- More robust to natural language variation  
- Easier to extend with new routes (just add more descriptions/examples)  
- Plays well with vector databases, RAG, and LLM-based tools

### 1.2 Where semantic routers fit in LLM systems

Common locations in an LLM stack:

- **Entry point router**  
  - Decides: “Is this a chit-chat question, a data lookup, a code generation request, or something else?”

- **Tool selection router**  
  - Selects which tool(s) a multi-tool agent should consider

- **Data source router**  
  - Chooses which knowledge base or index to query (HR policies vs product docs vs legal)

- **Model router**  
  - Routes between small, cheap models and large, powerful models based on complexity

> **Conceptual view:** A semantic router is a small, fast “brain” that decides *who* should handle a request, before the heavy work happens.

---

## 2. Core Building Blocks of a Semantic Router

Designing an effective semantic router means choosing and configuring four main building blocks:

1. **Embeddings model**  
2. **Vector store or similarity engine**  
3. **Route definitions** (what’s routable)  
4. **Decision policy** (how to choose & when to abstain)

### 2.1 Embeddings

Embeddings map text → **dense vectors** in a high-dimensional space where:

- Semantically similar texts are close  
- Dissimilar texts are far apart  

Common choices (as of late 2024):

- **OpenAI**  
  - `text-embedding-3-small` / `text-embedding-3-large`  
  - Docs: https://platform.openai.com/docs/guides/embeddings  

- **Cohere**  
  - `embed-english-v3`, `embed-multilingual-v3`  
  - Docs: https://docs.cohere.com/docs/text-embeddings  

- **Sentence-Transformers (open-source)**  
  - `all-MiniLM-L6-v2`, `all-mpnet-base-v2`, etc.  
  - Library: https://www.sbert.net/  

- **Other providers**  
  - Google Vertex AI `textembedding-gecko`  
  - Azure OpenAI embedding endpoints  
  - Mistral, Voyage AI, etc.

**Key considerations:**

- **Latency**: routers should be fast; small embedding models often suffice  
- **Cost**: per-token pricing vs free local models  
- **Language coverage**: multi-lingual use cases may need specific models  
- **Embedding space stability**: changing models can break previous similarity scores

### 2.2 Vector store / similarity engine

To assign a route, you typically:

1. Embed the **user input**
2. Compare it to embeddings representing each **route** (or route examples)
3. Choose the route with the highest similarity, if above a threshold

You can:

- Keep vectors in-memory (for small route sets)  
- Use a library like **FAISS** for efficient similarity search  
  - https://github.com/facebookresearch/faiss  
- Use a production-ready vector DB:  
  - **Pinecone**: https://www.pinecone.io/  
  - **Weaviate**: https://weaviate.io/  
  - **Qdrant**: https://qdrant.tech/  
  - **Chroma**: https://www.trychroma.com/  

For routing, you’re usually comparing against a **small number of routes** (dozens, sometimes hundreds). That means:

- You **don’t need** a heavyweight vector DB to get started  
- A simple NumPy array + cosine similarity may be enough

### 2.3 Route definitions

A **route** is an object representing “a possible destination.” At minimum:

- `name`: unique identifier, e.g., `"billing_support"`  
- `description`: natural language description of when this route should be used  
- (Optionally) `examples`: representative user queries  
- `handler`: reference to the function, chain, agent, model, or URL to call  

Example route definitions (conceptual):

```json
[
  {
    "name": "billing_support",
    "description": "Questions about invoices, payments, refunds, subscription plans or billing issues.",
    "examples": [
      "I want a refund for last month",
      "Why was I charged twice?",
      "How do I update my payment method?"
    ]
  },
  {
    "name": "technical_support",
    "description": "Questions about errors, login problems, bugs, integrations, APIs or technical issues.",
    "examples": [
      "I can't log into my account",
      "Your API is returning a 500 error",
      "My integration with Zapier stopped working"
    ]
  },
  {
    "name": "sales",
    "description": "Questions from potential customers about pricing, demos or feature comparisons.",
    "examples": [
      "Can I schedule a demo?",
      "Do you offer an enterprise plan?",
      "How do you compare to your competitors?"
    ]
  }
]
```

You can embed:

- Only `description`  
- Or `description + examples` (concatenated)  
- Or *each example separately* and aggregate at query time

> **Tip:** Examples often help more than long descriptions, especially for ambiguous domains.

### 2.4 Decision policy

Once you have similarities, you need a **policy** to turn them into a routing decision.

Common patterns:

- **Argmax with threshold**  
  - Choose the highest-similarity route  
  - If similarity < threshold → `fallback` or `no_route`

- **Top-K with filters**  
  - Look at top K routes; apply business rules (e.g., “don’t send to expensive model unless really needed”)

- **Abstain-first**  
  - Prefer to abstain when uncertain; may route to a safe fallback or ask a clarifying question

- **Ensemble decision**  
  - Combine semantic similarity with rule-based or metadata-based filters

---

## 3. Step‑by‑Step: Designing a Semantic Router

Before implementing anything, clarify **what exactly you want to route** and **why**.

### 3.1 Define the routing problem

Examples:

- “We have 3 main workflows: answer FAQs from our docs, execute database queries, or escalate to human support. We need to decide which to use per request.”

- “We have a cheap 7B model and an expensive 70B model. We want a router that sends simple requests to the small model and complex ones to the big model.”

Clarify:

1. **Inputs**: what’s being routed (user messages, whole conversations, tool results?)  
2. **Destinations**: tools, agents, workflows, models, indices  
3. **Constraints**: latency, cost, safety, regulatory constraints  
4. **Failure mode**: what happens when routing is uncertain or fails?

### 3.2 Specify routes

For each route:

- Write a **short, clear description** in natural language  
- Add **3–10 high-quality examples** per route  
- Decide the **handler** (e.g., function, chain, or service endpoint)  

Example (Python data structure):

```python
from dataclasses import dataclass
from typing import Callable, List, Optional

@dataclass
class Route:
    name: str
    description: str
    examples: List[str]
    handler: Callable  # Could also be a string identifier

routes = [
    Route(
        name="billing_support",
        description="Handle questions about invoices, payments, subscriptions, and refunds.",
        examples=[
            "I was charged twice this month.",
            "How do I update my credit card?",
            "Can I get a refund for last month's invoice?"
        ],
        handler=lambda x: handle_billing(x)
    ),
    # ... more routes ...
]
```

### 3.3 Choose embeddings and similarity metric

Consider:

- **Small & fast vs large & precise**  
- **Server-based vs local**  
- **Cosine similarity vs dot product vs Euclidean**  
  - In practice, cosine similarity is widely used for routing tasks

If you use `sentence-transformers`:

```python
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("all-MiniLM-L6-v2")  # Fast, good general-purpose baseline

def embed(texts):
    return model.encode(texts, normalize_embeddings=True)
```

Normalizing embeddings enables use of **dot product ≈ cosine similarity**.

### 3.4 Determine your policy & thresholds

You’ll likely need to experiment, but start with:

- **Similarity metric**: cosine similarity  
- **Threshold**: e.g., 0.55–0.75 range depending on model & domain  
- **Fallback route**: e.g., `"general_chat"` or “ask clarifying question”

Then refine using evaluation data (see Section 7).

---

## 4. Implementing a Basic Semantic Router in Python

Let’s build a small, self-contained semantic router that:

- Uses `sentence-transformers` for embeddings  
- Maintains route embeddings in memory  
- Performs cosine similarity for routing  
- Supports a confidence threshold and fallback

### 4.1 Setup

Install dependencies:

```bash
pip install sentence-transformers numpy
```

### 4.2 Minimal router implementation

```python
from dataclasses import dataclass
from typing import List, Callable, Optional, Tuple
import numpy as np
from sentence_transformers import SentenceTransformer

# ---------- Data structures ----------

@dataclass
class Route:
    name: str
    description: str
    examples: List[str]
    handler: Callable[[str], str]  # Input: user query, Output: response string

@dataclass
class RouteMatch:
    route: Optional[Route]
    score: float
    reason: str


# ---------- Embedding model ----------

model = SentenceTransformer("all-MiniLM-L6-v2")

def embed(texts: List[str]) -> np.ndarray:
    return model.encode(texts, normalize_embeddings=True)


# ---------- Define routes ----------

def handle_billing(query: str) -> str:
    return f"[Billing] Handling billing query: {query}"

def handle_technical(query: str) -> str:
    return f"[Technical] Handling technical query: {query}"

def handle_sales(query: str) -> str:
    return f"[Sales] Handling sales query: {query}"

def handle_fallback(query: str) -> str:
    return f"[Fallback] I'm not sure which department this is for. " \
           f"Could you clarify if this is about billing, technical issues, or sales?"


routes: List[Route] = [
    Route(
        name="billing_support",
        description=(
            "Questions about invoices, payments, refunds, subscription plans, "
            "or anything related to billing and charges."
        ),
        examples=[
            "I was charged twice this month",
            "How do I update my payment method?",
            "Can I get a refund for last month's invoice?"
        ],
        handler=handle_billing,
    ),
    Route(
        name="technical_support",
        description=(
            "Questions about product errors, bugs, login issues, API problems, "
            "integrations, or technical troubleshooting."
        ),
        examples=[
            "I can't log into my account",
            "Your API keeps returning a 500 error",
            "My integration with Zapier stopped working"
        ],
        handler=handle_technical,
    ),
    Route(
        name="sales",
        description=(
            "Questions from potential customers about pricing, product features, "
            "demos, contracts, or evaluating whether the product fits their needs."
        ),
        examples=[
            "Can I schedule a demo?",
            "Do you have an enterprise plan?",
            "How does your product compare to your competitors?"
        ],
        handler=handle_sales,
    ),
]

# Precompute route embeddings (simple approach: concatenate description + examples)
route_texts = [
    route.description + " " + " ".join(route.examples)
    for route in routes
]
route_embeddings = embed(route_texts)  # Shape: [num_routes, dim]


# ---------- Routing logic ----------

def route_query(
    query: str,
    threshold: float = 0.6
) -> RouteMatch:
    """Return the best-matching route (or None) and similarity score."""
    query_emb = embed([query])[0]  # Shape: [dim]

    # Cosine similarity = dot product since embeddings are normalized
    scores = route_embeddings @ query_emb  # Shape: [num_routes]
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])
    best_route = routes[best_idx]

    if best_score < threshold:
        return RouteMatch(
            route=None,
            score=best_score,
            reason=f"No route above threshold {threshold:.2f}; best was {best_route.name} ({best_score:.2f})."
        )

    return RouteMatch(
        route=best_route,
        score=best_score,
        reason=f"Matched route {best_route.name} with similarity {best_score:.2f}."
    )


def handle_query(query: str, threshold: float = 0.6) -> str:
    match = route_query(query, threshold=threshold)
    if match.route is None:
        # Fallback behavior
        print(f"[Router] {match.reason}")
        return handle_fallback(query)
    else:
        print(f"[Router] {match.reason}")
        return match.route.handler(query)


# ---------- Example usage ----------

if __name__ == "__main__":
    while True:
        q = input("User: ")
        if not q.strip():
            break
        response = handle_query(q)
        print("System:", response)
```

What this does:

1. Embeds each route once at startup  
2. On each query:
   - Embeds the query  
   - Computes similarity scores against each route  
   - Picks the best route if above the threshold  
   - Otherwise falls back

### 4.3 Notes & improvements

Potential improvements:

- **Per-example embeddings**:  
  - Embed each example; similarity = max or average across examples  
- **LLM explanation**:  
  - Ask an LLM to explain why it chose a route for logging/observability  
- **Hybrid rule+semantic**:  
  - Apply simple rules *before* semantic routing (e.g., high-risk keywords → human review)

---

## 5. Advanced Semantic Routing Patterns

Once you have a basic router, there are several powerful patterns to scale complexity and performance.

### 5.1 Hierarchical (multi‑stage) routing

Instead of one flat router with many routes:

1. **Top-level routes** for coarse-grained categories:
   - `support`, `sales`, `product_help`, `chit_chat`, `unsafe`  

2. Each top-level route has its own **sub-router**:
   - `support` → `billing_support`, `technical_support`, `account_support`  
   - `product_help` → `feature_A_help`, `feature_B_help`, …  

Advantages:

- Better performance when you have many routes (e.g., dozens or hundreds)  
- Easier mental model and maintainability  
- You can use specialized embedding models for each subtree if needed

### 5.2 Hybrid routing: rules + semantics

For many production systems, **pure semantic routing is not enough**:

- Regulatory or compliance constraints  
- Known edge cases  
- “Do not answer” or “always escalate” conditions

Typical hybrid pattern:

1. **Rule-based pre-filter**  
   - If query contains PII patterns or legal-critical terms → `legal_review` route  
   - If query includes known dangerous operations → block/flag

2. **Semantic router**  
   - For all remaining “safe” queries, use embeddings-based route selection

3. **Rule-based post-filter**  
   - Enforce additional constraints based on confidence scores, user attributes, etc.

### 5.3 Cost‑aware model routing (FrugalGPT‑style)

You can build a semantic router that chooses **which model** to use based on:

- **Complexity** of the request  
- **Domain** (e.g., coding vs casual conversation)  
- **Required quality** or latency

Typical stack:

- **Tier 1**: small, cheap model (few billion parameters) for simple queries  
- **Tier 2**: medium-sized model for moderate complexity  
- **Tier 3**: large, expensive model for hard queries

You can approximate complexity via:

- Query length, syntactic features  
- A simple classifier (embedding + MLP or LLM) that outputs complexity  
- Explicit user tier (e.g., free vs enterprise customers)

Reference work:

- **FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance (Gao et al., 2023)**  
  - arXiv: https://arxiv.org/abs/2305.05176  

### 5.4 Data‑source routing for RAG

In complex RAG systems, you may have:

- Product docs  
- Engineering runbooks  
- Legal documents  
- HR policies  
- Internal vs external knowledge

A semantic router can:

1. Classify the query into one or more **domains**  
2. Route to the appropriate **index** or **vector DB namespace**  
3. Optionally **fan out** to multiple sources and then merge/rerank results

Libraries like **LlamaIndex** and **LangChain** support this pattern natively (see Section 6).

### 5.5 Learning from feedback

You can let your router **improve over time**:

- Log: `(query, chosen_route, confidence, outcome)`  
- Label (manually or semi-automatically) whether the routing was correct  
- Train a lightweight classifier or fine-tune embeddings on routing data

Two paths:

1. **Embedding-level optimization**
   - Fine-tune an embedding model on your routed data so that queries and correct routes are closer

2. **Classifier on top of embeddings**
   - Use embeddings as features in a small neural network or logistic regression that outputs route probabilities

---

## 6. Using Existing Libraries & Frameworks

You don’t have to build everything from scratch. Several open-source frameworks include semantic routing primitives.

### 6.1 LangChain router chains

LangChain has **Router Chains** and **MultiPromptChain**:

- Docs:  
  - Router chains: https://python.langchain.com/docs/modules/chains/foundational/router  
  - Multi-prompt router: https://python.langchain.com/docs/modules/chains/popular/multi_prompt  

Key ideas:

- Each route is a **chain** with a description  
- An **LLM-based router** or embedding-based router decides which chain to call  
- You can implement both semantic and LLM routers easily

Example (simplified pseudo-code):

```python
from langchain.chains.router import MultiRouteChain
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.chat_models import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini")

# Define sub-chains
prompt_billing = PromptTemplate.from_template("You are a billing assistant. {input}")
billing_chain = LLMChain(llm=llm, prompt=prompt_billing)

prompt_tech = PromptTemplate.from_template("You are a technical support assistant. {input}")
tech_chain = LLMChain(llm=llm, prompt=prompt_tech)

router_chain = MultiRouteChain.from_chains(
    llm=llm,
    chains={
        "billing": billing_chain,
        "technical": tech_chain,
    },
    default_chain=billing_chain  # or some fallback
)

response = router_chain.run("Why was I charged twice?")
print(response)
```

LangChain’s router chain originally focused on **LLM-based routers** (asking an LLM which chain to call), but you can also integrate embedding-based routers.

### 6.2 LlamaIndex RouterQueryEngine

LlamaIndex supports a **router query engine** that sends a query to the best sub-engine (index or tool):

- Docs: https://docs.llamaindex.ai/en/stable/module_guides/querying/router_query_engine/  

Basic idea:

- Each sub-index has a description  
- A router (often LLM-based) picks the most relevant sub-index  
- The chosen index then handles the query

Example (pseudo-code):

```python
from llama_index import (
    VectorStoreIndex,
    RouterQueryEngine,
    QueryEngineTool,
    SimpleDirectoryReader,
)

# Build separate indices for two domains
billing_docs = SimpleDirectoryReader("./docs/billing").load_data()
tech_docs = SimpleDirectoryReader("./docs/technical").load_data()

billing_index = VectorStoreIndex.from_documents(billing_docs)
tech_index = VectorStoreIndex.from_documents(tech_docs)

billing_engine = billing_index.as_query_engine()
tech_engine = tech_index.as_query_engine()

tools = [
    QueryEngineTool.from_defaults(
        query_engine=billing_engine,
        description="Use this for questions about invoices, charges, and payments.",
    ),
    QueryEngineTool.from_defaults(
        query_engine=tech_engine,
        description="Use this for technical issues, API questions, and bugs.",
    ),
]

router_engine = RouterQueryEngine.from_defaults(
    query_engine_tools=tools,
    default_query_engine=billing_engine,
)

response = router_engine.query("Why am I getting a 500 error from your API?")
print(response)
```

LlamaIndex usually uses an **LLM to decide** which tool/index to use based on descriptions, but you can integrate your own embedding-based router for more control.

### 6.3 `semantic-router` (BerriAI)

There is a dedicated library named **semantic-router** from BerriAI:

- GitHub: https://github.com/BerriAI/semantic-router  

Features (at high level):

- Intent routing using sentence embeddings  
- Fast, production-friendly implementation  
- Integration with popular LLM frameworks

It’s a good starting point if you want a focused, batteries-included router library without building everything yourself.

### 6.4 Semantic Kernel & planners

Microsoft’s **Semantic Kernel** has the notion of **planners** and **skills**:

- Repo: https://github.com/microsoft/semantic-kernel  

While not framed specifically as “semantic routing,” planners:

- Select which **skills** (tools) to call based on a natural language request  
- Can be thought of as a more dynamic, plan-and-route mechanism built on LLMs

If you’re in the .NET or C# ecosystem, Semantic Kernel provides many of the necessary primitives for semantic tool selection and routing.

---

## 7. Evaluating and Debugging Semantic Routers

A semantic router is only as good as its behavior **under real traffic**. You need a plan for evaluation and observability.

### 7.1 Build a labeled routing dataset

Start by collecting:

- Real user queries (anonymized if necessary)  
- For each, the **correct route** (labeled by humans or domain experts)

Aim for:

- At least **50–100 examples per route** for initial evaluation  
- More for critical routes or highly ambiguous domains

Store something like:

```json
{
  "query": "I want to downgrade my subscription.",
  "true_route": "billing_support"
}
```

### 7.2 Metrics

Common metrics:

- **Accuracy**: fraction of queries routed to the correct route  
- **Top‑K accuracy** (if you use multi-route suggestions)  
- **Abstain rate**: fraction of queries where router chooses `no_route`  
- **Confusion matrix**: which routes get confused with which others  

In some settings, misrouting is more harmful than abstaining; you might prefer:

- Lower accuracy but **higher safety** (more abstentions)

### 7.3 Offline evaluation loop

1. Freeze a version of your router (embeddings, routes, thresholds)  
2. Run all labeled queries through it  
3. Compute metrics; inspect errors  

Iterate on:

- Route descriptions and examples  
- Thresholds  
- Embedding model choice  
- Hierarchical vs flat routing

### 7.4 Online monitoring

In production:

- Log every routing decision:
  - `query`, `selected_route`, `score`, `alternative_routes`, `user_id`, `timestamp`  
- Sample a subset for **manual review** each week  
- Track:
  - Spikes in routing errors  
  - Highly ambiguous queries  
  - New intents that don’t fit existing routes

> **Best practice:** Add a simple “Was this helpful?” or “Wrong department?” feedback mechanism for users; tie that back to router metrics.

### 7.5 Debugging misroutes

When you find misrouted queries:

1. Inspect **similarity scores**: was the model unsure (low scores) or confident-but-wrong?  
2. Check whether:
   - The true route has poor or missing examples  
   - Another route’s description is too broad  
   - The embedding model struggles with specific jargon or languages

Then fix by:

- Improving or rebalancing examples  
- Splitting overloaded routes into smaller ones  
- Using a more domain-tuned embedding model  
- Lowering the threshold and adding more nuanced fallbacks

---

## 8. Common Pitfalls and Best Practices

### 8.1 Pitfalls

1. **Too many overlapping routes**  
   - Slightly different descriptions that confuse both the model and humans  
   - Solution: merge or clarify routes; use hierarchical routing

2. **No ability to abstain**  
   - Forcing a route even when similarity is low → bad user experience  
   - Solution: use a threshold and a fallback route

3. **Route descriptions that are vague or marketing-fluff**  
   - Embeddings thrive on concrete, specific text  
   - Solution: write clear, operational descriptions (“Handle X when Y…”) with examples

4. **Ignoring drift over time**  
   - Product & user behavior changes; router becomes stale  
   - Solution: continuously log & review, update routes and examples regularly

5. **Relying solely on semantic routing for safety-critical decisions**  
   - Some queries need rule-based, explicit guards  
   - Solution: use hybrid routing and explicit safety filters

### 8.2 Best practices

- Start **simple**: a handful of well-defined routes and a fast embedding model  
- Use **examples** generously—often more helpful than long descriptions  
- Always implement a **safe fallback** route  
- Add **logging & metrics** from day one  
- Document routes clearly (for engineers *and* domain experts)  
- Involve users or operators in labeling misroutes and improving the router

---

## 9. Conclusion

Semantic routing is becoming a foundational pattern in modern LLM systems.

By replacing brittle keyword rules with **embedding-based** (or LLM-based) decisions, a semantic router lets you:

- Seamlessly orchestrate multiple tools, workflows, and models  
- Adapt to diverse, natural language inputs  
- Scale your system as you add more capabilities and domains  

A good semantic router is:

- Conceptually simple (routes + embeddings + similarity + thresholds)  
- Carefully designed (clear route specs, thresholds, fallbacks)  
- Continuously monitored and improved via real-world data  

Whether you build your own minimal router or use frameworks like **LangChain**, **LlamaIndex**, or **semantic-router**, understanding the underlying concepts helps you:

- Debug misroutes  
- Tune for cost, latency, and safety  
- Communicate clearly with stakeholders about how the system behaves  

If you’re building multi-tool agents, complex RAG systems, or multi-model stacks, investing in a **well-designed semantic router** will pay off quickly—in reliability, user experience, and maintainability.

---

## 10. Resources and Further Reading

Below are curated resources (with links) to dive deeper into semantic routing and related topics.

### 10.1 Conceptual & research resources

- **FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance**  
  - Gao et al., 2023 (arXiv)  
  - https://arxiv.org/abs/2305.05176  

- **Cohere: Semantic Routing: Dynamic Selection of Language Models**  
  - High-level introduction and examples of semantic routing in production (model selection context)  
  - https://txt.cohere.com/semantic-routing/  

- **Self-Discovering Language Model Routes (Liu et al., 2023)**  
  - Research on automatically discovering routing strategies between models  
  - https://arxiv.org/abs/2306.16416  

### 10.2 Libraries & frameworks

- **LangChain Router Chains**  
  - Router docs: https://python.langchain.com/docs/modules/chains/foundational/router  
  - Multi-prompt chain: https://python.langchain.com/docs/modules/chains/popular/multi_prompt  

- **LlamaIndex Router Query Engine**  
  - Docs: https://docs.llamaindex.ai/en/stable/module_guides/querying/router_query_engine/  

- **`semantic-router` (BerriAI)**  
  - GitHub: https://github.com/BerriAI/semantic-router  

- **Microsoft Semantic Kernel**  
  - GitHub: https://github.com/microsoft/semantic-kernel  

### 10.3 Embedding models and tools

- **Sentence-Transformers**  
  - Site: https://www.sbert.net/  
  - GitHub: https://github.com/UKPLab/sentence-transformers  

- **OpenAI Embeddings**  
  - Docs: https://platform.openai.com/docs/guides/embeddings  

- **Cohere Embeddings**  
  - Docs: https://docs.cohere.com/docs/text-embeddings  

### 10.4 Vector databases & similarity search

- **FAISS** (Facebook AI Similarity Search)  
  - GitHub: https://github.com/facebookresearch/faiss  

- **Pinecone**