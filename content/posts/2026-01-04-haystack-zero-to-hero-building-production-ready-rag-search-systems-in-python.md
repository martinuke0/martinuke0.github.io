---
title: "Haystack Zero to Hero: Building Production-Ready RAG & Search Systems in Python"
date: "2026-01-04T11:21:01.448"
draft: false
tags: ["haystack", "rag", "python", "llm", "search"]
---

## Introduction

Retrieval-augmented generation (RAG), semantic search, and intelligent question-answering are now core building blocks of modern AI applications. But wiring together vector databases, file converters, retrievers, LLMs, and evaluation in a robust way is non‑trivial.

Haystack, an open‑source Python framework by deepset, is designed to make this tractable: it gives you a full toolkit to ingest data, search it efficiently, query it with LLMs, run evaluation, and deploy to production.

This “zero to hero” guide will walk you from first contact with Haystack to building a realistic, production‑ready RAG system. You’ll see how to:

- Ingest and preprocess data from common formats (PDF, HTML, DOCX, Markdown)
- Choose and configure document stores (in‑memory, Elasticsearch, OpenSearch, Qdrant, Weaviate, etc.)
- Build sparse, dense, and hybrid retrievers
- Connect LLMs (OpenAI, Anthropic, local models) for RAG-style question answering
- Orchestrate everything using Haystack pipelines
- Evaluate and monitor your system
- Apply best practices for performance, quality, and maintainability

All examples use Python and the modern Haystack 2.x concepts (components and pipelines).

---

## 1. What Is Haystack and Why Use It?

Haystack is a framework for building search, question-answering, and RAG applications. It abstracts away most of the boilerplate and plumbing typically needed to:

- Parse and chunk data
- Store and index documents
- Retrieve relevant context
- Call LLMs or readers
- Orchestrate complex workflows
- Evaluate quality and performance

### 1.1 Core problems Haystack solves

Haystack is especially useful when:

- You have *private* or *domain-specific* data (wikis, manuals, tickets, contracts, logs)
- You want *accurate* answers grounded in that data (not generic LLM hallucinations)
- You care about *traceability* (citations, which documents were used)
- You want to *iterate quickly* from prototype to production

Typical use cases:

- Internal knowledge bases and chatbots
- Developer or product documentation assistants
- Legal or compliance search
- Customer support assistants
- Research & analysis tools (multi-document synthesis)
- Enterprise search portals

### 1.2 Haystack 2.x at a glance

The crucial concepts in Haystack 2.x:

- **Document** – a text chunk plus metadata
- **DocumentStore** – where Documents live (in‑memory, Elasticsearch, vector DBs, etc.)
- **Components** – modular building blocks (retrievers, generators/LLM, rankers, writers, converters, etc.)
- **Pipelines** – directed graphs that connect components into indexing, search, or RAG workflows

This modularity makes it easy to swap implementations (e.g., BM25 vs dense retriever, OpenAI vs local LLM) without rewriting your entire app.

---

## 2. Core Concepts You Must Understand

Before writing any code, lock in these mental models.

### 2.1 Documents

A `Document` in Haystack is usually a *chunk* of text plus metadata:

- `content`: the text
- `meta`: dictionary of metadata (e.g., `{"source": "handbook.pdf", "page": 7, "section": "Leave policy"}`)

Chunking is key: instead of indexing entire 200‑page PDFs as one document, you split into smaller paragraphs or sections. This:

- Improves retrieval accuracy
- Reduces LLM token usage
- Makes citations more precise

```python
from haystack import Document

doc = Document(
    content="Employees are entitled to 25 days of paid vacation per year.",
    meta={"source": "employee_handbook.pdf", "page": 12, "category": "benefits"}
)
```

### 2.2 DocumentStores

A `DocumentStore` is the backend that stores and indexes your documents. Haystack supports many:

- **InMemoryDocumentStore** – fast, great for development & tests
- **SQLite / SQL-based stores** – simple, local persistence
- **Elasticsearch / OpenSearch** – mature, scalable text search
- **Vector DBs** (Qdrant, Weaviate, Pinecone, etc.) – optimized for dense embeddings
- **PostgreSQL + pgvector / other hybrid stores**

You can switch DocumentStores without changing your high‑level logic much.

### 2.3 Components

Components are reusable blocks that operate on data in a pipeline. Common ones:

- **File converters** – PDFToDocument, MarkdownToDocument, HTMLToDocument
- **Preprocessors** – split text into chunks, clean formatting
- **Writers** – write Documents into a DocumentStore
- **Retrievers** – pull relevant Documents from the store (BM25, dense embeddings, hybrid)
- **Rankers** – re‑rank retrieved docs
- **Generators** – call LLMs to generate answers (RAG)
- **Prompt builders** – build dynamic prompts from templates and inputs
- **Routers / classifiers** – decide which branch of a pipeline to follow

### 2.4 Pipelines

A `Pipeline` wires components into a directed graph. Common patterns:

- **Indexing pipeline**: convert → preprocess → write to store
- **Query pipeline**: retrieve → (rank) → (prompt) → generate answer
- **Hybrid / advanced pipelines**: multiple retrievers, query routing, answer post‑processing, evaluation branches

```python
from haystack import Pipeline

pipe = Pipeline()
pipe.add_component("retriever", retriever)
pipe.add_component("generator", generator)
pipe.connect("retriever.documents", "generator.documents")
```

Inputs and outputs are wired by name. At runtime you call:

```python
result = pipe.run({"retriever": {"query": "your question"}})
```

---

## 3. Getting Started: Installation and Minimal Example

### 3.1 Installation

Use Python 3.9+ and install via pip:

```bash
pip install farm-haystack[all]
```

Or, for a leaner install, pick relevant extras (check the official docs for up‑to‑date extras):

```bash
# Basic core
pip install farm-haystack

# With common backends and tools
pip install "farm-haystack[elasticsearch,opensearch,faiss,preprocessing,ocr]"
```

> **Note**: Names of extras can change; check the [Haystack documentation](https://docs.haystack.deepset.ai) for the latest recommended installation commands.

### 3.2 A minimal “Hello World” Haystack pipeline

This example:

1. Creates an in‑memory document store
2. Indexes a few toy documents
3. Builds a BM25 retriever
4. Uses an OpenAI LLM as a generator to answer a question with RAG

#### Step 1: Basic setup

```python
import os
from haystack import Pipeline, Document
from haystack.document_stores.in_memory import InMemoryDocumentStore
from haystack.components.writers import DocumentWriter
from haystack.components.retrievers import InMemoryBM25Retriever
from haystack.components.generators import OpenAIGenerator

os.environ["OPENAI_API_KEY"] = "YOUR_OPENAI_KEY"  # or pass explicitly
```

#### Step 2: Create a DocumentStore and index documents

```python
document_store = InMemoryDocumentStore()

# Some simple example documents
docs = [
    Document(content="Haystack is an open-source framework for search and question answering."),
    Document(content="Haystack supports RAG pipelines that connect your data to LLMs."),
    Document(content="You can use BM25 or dense vector search to retrieve relevant documents."),
]

writer = DocumentWriter(document_store=document_store)
writer.run(documents=docs)  # For small data, you can call the component directly
```

#### Step 3: Create retriever and generator components

```python
retriever = InMemoryBM25Retriever(document_store=document_store)

generator = OpenAIGenerator(
    api_key=os.environ["OPENAI_API_KEY"],
    model="gpt-4o-mini",   # pick a model you have access to
    max_tokens=256
)
```

#### Step 4: Build the query pipeline

```python
rag_pipeline = Pipeline()
rag_pipeline.add_component("retriever", retriever)
rag_pipeline.add_component("generator", generator)

# Wire documents from retriever to generator
rag_pipeline.connect("retriever.documents", "generator.documents")
```

#### Step 5: Ask a question

```python
query = "What is Haystack and what can I do with it?"

result = rag_pipeline.run(
    {
        "retriever": {"query": query, "top_k": 3},
        "generator": {"prompt": "Answer the question using the provided documents."}
    }
)

print(result["generator"]["replies"][0])
```

You’ve just built a minimal RAG system: the retriever fetches relevant content, and the LLM uses it to answer the question.

---

## 4. Preparing and Ingesting Your Data

Real‑world projects start with messy data: PDFs, web pages, docs, Markdown, HTML, emails. Haystack provides converters and preprocessors to transform this into clean Documents.

### 4.1 Common ingestion patterns

Typical indexing pipeline:

1. **Fetch/locate files** (filesystem, S3, GCS, database export)
2. **Convert files to text → Documents** (one Document per page/section)
3. **Preprocess documents** (cleaning, splitting, metadata)
4. **Write to DocumentStore**

### 4.2 File converters

Haystack ships with converters for many formats (names may differ slightly by version):

- `PDFToDocument` – reads PDFs
- `MarkdownToDocument`
- `HTMLToDocument`
- `TextFileToDocument`
- `DocxToDocument`

Example: index all PDFs from a folder into an Elasticsearch store.

```python
from pathlib import Path

from haystack import Pipeline
from haystack.document_stores import ElasticsearchDocumentStore
from haystack.components.converters import PDFToDocument
from haystack.components.preprocessors import DocumentSplitter, DocumentCleaner
from haystack.components.writers import DocumentWriter

# 1. Document store
document_store = ElasticsearchDocumentStore(
    host="localhost",
    port=9200,
    index="company_knowledge",
    search_fields=["content"]
)

# 2. Components
pdf_converter = PDFToDocument()
cleaner = DocumentCleaner(
    remove_empty_lines=True,
    remove_whitespace=True,
    remove_numeric_tables=True
)
splitter = DocumentSplitter(
    split_by="word",
    split_length=200,
    split_overlap=20
)
writer = DocumentWriter(document_store=document_store)

# 3. Indexing pipeline
indexing = Pipeline()
indexing.add_component("converter", pdf_converter)
indexing.add_component("cleaner", cleaner)
indexing.add_component("splitter", splitter)
indexing.add_component("writer", writer)

indexing.connect("converter.documents", "cleaner.documents")
indexing.connect("cleaner.documents", "splitter.documents")
indexing.connect("splitter.documents", "writer.documents")

# 4. Run indexing
pdf_files = list(Path("data/pdfs").glob("*.pdf"))
indexing.run({"converter": {"sources": pdf_files}})
```

> **Tip**: Keep splits small enough (e.g., 150–300 words) to be retrievable and fit into LLM context, but large enough to preserve meaning.

### 4.3 Metadata and filters

Attach metadata as early as possible. This allows you to:

- Filter search by `source`, `language`, `customer_id`, `category`
- Segment your index by tenant or product
- Support faceted search or filtering in your UI

Example: adding metadata during conversion:

```python
documents = pdf_converter.run(
    sources=[Path("policies/leave_policy.pdf")],
    meta={"category": "HR", "policy_type": "leave"}
)["documents"]
```

Later, you can filter:

```python
result = rag_pipeline.run(
    {
        "retriever": {
            "query": "How many vacation days do I get?",
            "filters": {"category": ["HR"]},
            "top_k": 5,
        }
    }
)
```

---

## 5. Choosing and Configuring a Document Store

The DocumentStore choice is one of the most important decisions.

### 5.1 Quick decision guide

- **Just prototyping / learning**  
  → `InMemoryDocumentStore`

- **Single machine, small‑to‑medium data, simple setup**  
  → SQLiteDocumentStore or PostgreSQLDocumentStore with pgvector (if using embeddings)

- **Need strong keyword search, logs, analytics, scale‑out**  
  → `ElasticsearchDocumentStore` or `OpenSearchDocumentStore`

- **Heavy vector workloads, ANN search, high recall / speed requirements**  
  → `QdrantDocumentStore`, `WeaviateDocumentStore`, `PineconeDocumentStore`, or other vector DB

- **Hybrid search (BM25 + vectors)**  
  → Stores supporting both text and embeddings (e.g., Elasticsearch with dense_vector, some vector DBs with metadata text search)

### 5.2 Example: Qdrant as vector store

```python
from haystack.document_stores import QdrantDocumentStore

document_store = QdrantDocumentStore(
    host="localhost",
    port=6333,
    index="docs",
    embedding_dim=768,  # match your embedding model
    recreate_index=False
)
```

Once configured, the rest of the Haystack code uses the same abstractions.

---

## 6. Retrieval: Sparse, Dense, and Hybrid

Retrieval is the heart of your RAG system. Poor retrieval leads to poor answers, no matter how strong your LLM is.

### 6.1 Sparse (BM25) retrievers

Sparse retrievers use term‑based ranking (BM25). They:

- Work well with traditional search (keywords, exact phrases)
- Require no embedding model
- Are robust for low‑resource or multilingual settings if your index supports it

Example (In‑memory BM25):

```python
from haystack.components.retrievers import InMemoryBM25Retriever
from haystack.document_stores.in_memory import InMemoryDocumentStore

document_store = InMemoryDocumentStore()
# Assume documents are already written

bm25_retriever = InMemoryBM25Retriever(document_store=document_store)

docs = bm25_retriever.run(query="reset password steps", top_k=5)["documents"]
for d in docs:
    print(d.content[:120], "...")
```

For Elasticsearch/OpenSearch, use the specific retriever component (names vary slightly per version, e.g., `ElasticsearchBM25Retriever`).

### 6.2 Dense (embedding) retrievers

Dense retrievers convert queries and documents into vectors and use approximate nearest neighbor (ANN) search. They:

- Handle semantic similarity (different wording, same meaning)
- Are often better for long, natural-language questions
- Require an embedding model (e.g., SentenceTransformers, OpenAI embeddings)

Example: using an embedding-based retriever with a HuggingFace model:

```python
from haystack.components.retrievers import DenseRetriever
from haystack.document_stores import QdrantDocumentStore

# Vector store
document_store = QdrantDocumentStore(
    host="localhost",
    port=6333,
    index="docs",
    embedding_dim=768
)

# Dense retriever
dense_retriever = DenseRetriever(
    document_store=document_store,
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    batch_size=32,
)
```

You’ll typically run a **separate pipeline** to create and store embeddings for all documents:

```python
from haystack import Pipeline
from haystack.components.writers import DocumentWriter

writer = DocumentWriter(document_store=document_store)

indexing = Pipeline()
indexing.add_component("embedder", dense_retriever)  # many versions reuse the same class as an embedder
indexing.add_component("writer", writer)

indexing.connect("embedder.documents", "writer.documents")

# Suppose you already have docs in memory or from a converter
indexing.run({"embedder": {"documents": docs}})
```

> **Note**: Exact API may differ slightly depending on Haystack version (some versions have dedicated embedding components like `DocumentEmbedder`); always check the current docs.

### 6.3 Hybrid retrievers

Hybrid retrieval combines sparse and dense approaches to get the best of both worlds:

- BM25 captures exact matches and rare terms
- Dense retriever captures semantic similarity

Strategies include:

- **Union**: combine results from both, deduplicate, then re‑rank
- **Weighted sum**: combine scores with weights (α * sparse + β * dense)
- **Cascade**: use one as candidate generator, the other as re‑ranker

Example hybrid pipeline (conceptual):

```python
from haystack import Pipeline
from haystack.components.retrievers import InMemoryBM25Retriever, DenseRetriever
from haystack.components.rankers import TransformersRanker

bm25 = InMemoryBM25Retriever(document_store=document_store)
dense = DenseRetriever(
    document_store=document_store,
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
)

ranker = TransformersRanker(model_name_or_path="cross-encoder/ms-marco-MiniLM-L-6-v2", top_k=10)

pipe = Pipeline()
pipe.add_component("bm25", bm25)
pipe.add_component("dense", dense)
pipe.add_component("ranker", ranker)

# Combine outputs (pseudo-code – actual combination may use a Router or custom component)
pipe.connect("bm25.documents", "ranker.documents")
pipe.connect("dense.documents", "ranker.documents")

res = pipe.run({"bm25": {"query": "refund policy"}, "dense": {"query": "refund policy"}})
```

If you need precise control over combination logic, consider writing a small custom component.

---

## 7. Adding LLMs and Building RAG Pipelines

With retrieval in place, you can build full RAG systems by adding:

- A **PromptBuilder** to construct rich prompts
- A **Generator** component that calls an LLM

### 7.1 Prompt building

`PromptBuilder` lets you define templates that combine:

- User query
- Retrieved documents (e.g., `documents` list)
- Other context or system instructions

Example:

```python
from haystack.components.builders import PromptBuilder

template = """
You are a helpful assistant that answers questions using ONLY the provided context.

Context:
{% for doc in documents %}
- {{ doc.content }}
{% endfor %}

Question: {{ query }}

If the answer is not in the context, say you don't know.
Answer:
"""

prompt_builder = PromptBuilder(template=template)
```

### 7.2 LLM generators

Haystack provides generator components for different providers. Common ones include:

- `OpenAIGenerator`
- `HuggingFaceLocalGenerator`
- `AzureOpenAIGenerator`
- (and others depending on version)

Example: combine retriever, prompt builder, and generator into a full RAG pipeline.

```python
from haystack import Pipeline
from haystack.components.generators import OpenAIGenerator
from haystack.components.retrievers import InMemoryBM25Retriever
from haystack.components.builders import PromptBuilder
from haystack.document_stores.in_memory import InMemoryDocumentStore

document_store = InMemoryDocumentStore()
# Assume docs already indexed

retriever = InMemoryBM25Retriever(document_store=document_store)

template = """
You are a domain expert. Use the context to answer the question.
Provide a concise, factual answer and list the sources at the end.

Context:
{% for doc in documents %}
[Source: {{ doc.meta.source | default("unknown") }}]
{{ doc.content }}

{% endfor %}

Question: {{ query }}

Answer (include a "Sources:" section with the file names):
"""

prompt_builder = PromptBuilder(template=template)

generator = OpenAIGenerator(model="gpt-4o-mini")

rag = Pipeline()
rag.add_component("retriever", retriever)
rag.add_component("prompt_builder", prompt_builder)
rag.add_component("generator", generator)

rag.connect("retriever.documents", "prompt_builder.documents")
rag.connect("prompt_builder.prompt", "generator.prompt")

query = "What does our leave policy say about parental leave?"

result = rag.run(
    {
        "retriever": {"query": query, "top_k": 5},
        "prompt_builder": {"query": query},
    }
)

print(result["generator"]["replies"][0])
```

### 7.3 Controlling hallucinations and style

You can steer LLM behavior via your prompt and parameters:

- Explicitly instruct: “Use only the provided context.”
- Ask it to say “I don’t know” if context is insufficient
- Limit answer length (e.g., “Answer in fewer than 150 words.”)
- Use temperature, top_p, etc.

Example with stricter instructions:

```python
strict_template = """
You are a cautious assistant. Answer ONLY with information from the context.

Context:
{% for doc in documents %}
{{ doc.content }}
{% endfor %}

Question: {{ query }}

If the answer is not directly supported by the context, reply:
"I don't know based on the provided documents."

Answer:
"""
```

---

## 8. Orchestrating Complex Workflows with Pipelines

Real systems often need more than “retrieve → generate”. Haystack’s graph pipelines let you create:

- Branching logic (different retrievers per domain)
- Pre‑/post‑processing (query rewriting, answer formatting)
- Multi‑step workflows (e.g., “classify → retrieve → summarize → evaluate”)

### 8.1 Multi-branch pipeline example

Scenario: if the question is about “billing”, use a billing-specific index; otherwise, use the general index.

1. A classifier routes the query
2. Two different retrievers exist (billing, general)
3. Both feed into the same generator

Conceptually:

```plaintext
query
  → classifier
      → billing_retriever → generator
      → general_retriever → generator
```

Pseudo‑code (APIs differ between Haystack versions):

```python
from haystack import Pipeline
from haystack.components.routers import QueryClassifier
from haystack.components.retrievers import InMemoryBM25Retriever
from haystack.components.generators import OpenAIGenerator

billing_store = ...
general_store = ...

billing_retriever = InMemoryBM25Retriever(document_store=billing_store)
general_retriever = InMemoryBM25Retriever(document_store=general_store)
classifier = QueryClassifier(  # heuristic or LLM-based router
    rules={"billing": ["invoice", "payment", "refund", "billing"], "general": []}
)

generator = OpenAIGenerator(model="gpt-4o-mini")

pipe = Pipeline()
pipe.add_component("classifier", classifier)
pipe.add_component("billing_retriever", billing_retriever)
pipe.add_component("general_retriever", general_retriever)
pipe.add_component("generator", generator)

# Wire classifier outputs to retrievers (actual API uses conditions or output fields)
pipe.connect("classifier.billing_query", "billing_retriever.query")
pipe.connect("classifier.general_query", "general_retriever.query")

pipe.connect("billing_retriever.documents", "generator.documents")
pipe.connect("general_retriever.documents", "generator.documents")
```

This pattern is powerful when your corpus is naturally segmented (per product, per department, per tenant).

### 8.2 Custom components

If built‑in components don’t cover your needs, you can create your own:

```python
from haystack import component

@component
class LowercasePreprocessor:
    @component.output_types(text=str)
    def run(self, text: str):
        return {"text": text.lower()}
```

Then:

```python
pipe = Pipeline()
pipe.add_component("lower", LowercasePreprocessor())
# connect accordingly
```

Custom components are excellent for:

- Normalizing queries
- Custom scoring or ranking
- Business rule‑based filtering
- Integrations with internal systems

---

## 9. Evaluation, Testing, and Monitoring

A RAG system is only as valuable as its answers. You should measure and monitor:

- Retrieval quality
- Answer correctness
- Latency, throughput, and failure rates

### 9.1 Retrieval evaluation

If you have labeled data (questions with known relevant documents), you can compute:

- Recall@k
- Precision@k
- Mean Reciprocal Rank (MRR)
- nDCG

Haystack’s evaluation utilities (names vary by version) usually accept:

- A set of queries
- For each, a set of relevant document IDs
- A retriever to test

Example (high‑level, pseudo‑code):

```python
from haystack.evaluation import Evaluator  # or similar in your version

evaluator = Evaluator(
    document_store=document_store,
    retriever=retriever,
    metrics=["recall_at_5", "mrr"]
)

scores = evaluator.evaluate(queries, labels)
print(scores)
```

If you don’t have labels, you can:

- Create a small labeled set manually
- Use synthetic data (e.g., automatically generate Q&A from docs)
- Use LLMs as weak judges (with caution)

### 9.2 End-to-end answer evaluation

For RAG, you care about answer quality:

- Faithfulness (grounded in context)
- Relevance (addresses question)
- Completeness
- Style and tone

Options:

- **Human evaluations** (gold standard)
- **LLM‑as‑a‑judge** patterns (OpenAI’s “evals” style)
- **Automatic heuristics** (e.g., overlap with reference answers)

Haystack offers components to support LLM‑based evaluation in some versions or you can write your own evaluation pipeline.

### 9.3 Monitoring in production

At minimum, log:

- Query text
- Retrieved document IDs and scores
- Prompt and LLM response
- Latency per stage (retrieve, generate)
- Errors and fallbacks

Add a feedback mechanism:

- Thumbs up/down
- “Was this answer helpful?” rating
- Ability for users to flag incorrect answers

Use this feedback for:

- Offline analysis
- Improving retrieval models
- Prompt iteration
- Training custom models

---

## 10. Taking Haystack to Production

Once you’re happy with quality, you need to:

- Expose your pipeline as a web API
- Handle concurrency and scaling
- Manage secrets and configuration
- Monitor and log

### 10.1 Serving a pipeline via FastAPI

A simple approach is to wrap your pipeline in a FastAPI app.

```python
from fastapi import FastAPI
from pydantic import BaseModel
from haystack import Pipeline

app = FastAPI()

# Build or load your pipeline (e.g., from config)
rag_pipeline = build_rag_pipeline()  # your function

class QueryRequest(BaseModel):
    query: str
    top_k: int = 5

class AnswerResponse(BaseModel):
    answer: str
    sources: list[str]

@app.post("/query", response_model=AnswerResponse)
def query(request: QueryRequest):
    result = rag_pipeline.run(
        {
            "retriever": {"query": request.query, "top_k": request.top_k},
            "prompt_builder": {"query": request.query},
        }
    )
    answer = result["generator"]["replies"][0]
    docs = result["retriever"]["documents"]
    sources = list({d.meta.get("source", "unknown") for d in docs})
    return AnswerResponse(answer=answer, sources=sources)
```

Run with Uvicorn:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

### 10.2 Performance tips

- **Use batching** for embeddings and LLM calls when appropriate
- **Cache**:
  - Query → retrieved docs
  - Prompt → LLM response (for frequently repeated queries)
- **Optimize retrieval**:
  - Use ANN indexes for dense search
  - Reduce `top_k` to just what you need (e.g., 5–10)
- **Control LLM costs**:
  - Use smaller models if acceptable
  - Limit context size (number of documents)
  - Truncate long documents

### 10.3 Configuration and deployment

- Store secrets (API keys, DB passwords) in environment variables or a secret manager
- Parameterize:
  - Model names
  - Index names
  - Retrievers (BM25 vs dense vs hybrid)
- Use containerization (Docker) and orchestration (Kubernetes) if scaling out
- For managed options, consider deepset Cloud or similar hosted Haystack offerings

---

## 11. Advanced Patterns: Going from Hero to Superhero

Once you have a solid RAG system, you can explore advanced capabilities.

### 11.1 Multi-hop / multi-step RAG

Complex questions sometimes require:

- Decomposing a question into sub‑questions
- Running multiple retrieval rounds
- Combining answers

Example flows:

1. Use an LLM to rewrite the user query into multiple sub‑queries
2. Retrieve documents for each sub‑query
3. Aggregate or summarize across all retrieved content

This can be implemented as a multi‑stage pipeline:

```plaintext
user_query
  → question_decomposer (LLM)
    → retriever (for each sub-query)
      → aggregator/summarizer (LLM)
```

### 11.2 Agents and tools

Agentic patterns involve:

- An LLM deciding which tools/components to call
- Iteratively refining queries
- Calling APIs (e.g., CRM, SQL databases) alongside document retrieval

Haystack supports building tool‑like components and letting an LLM orchestrate them. This is more complex but powerful when you need dynamic, multi‑step reasoning workflows.

### 11.3 Query rewriting and enrichment

Improve retrieval by:

- Expanding queries with synonyms
- Reformulating long natural-language questions into concise queries
- Adding metadata filters based on user profile or context

You can add a pre‑retrieval component for query rewriting using an LLM or heuristic rules.

### 11.4 Personalization and multi-tenancy

For multi‑tenant systems:

- Add `tenant_id` or `customer_id` to document metadata
- Enforce filters in the retriever so each user only sees their own data
- Use separate indexes per tenant for strong isolation when needed

For personalization:

- Track user history (previous queries and interactions)
- Use that context when building prompts or filters

---

## 12. Common Pitfalls and Best Practices

### 12.1 Pitfalls

1. **Indexing entire documents without chunking**  
   Leads to poor retrieval and huge prompts.

2. **Relying solely on the LLM without strong retrieval**  
   Produces hallucinations and brittle behavior.

3. **Ignoring metadata**  
   Makes filtering, access control, and analytics difficult later.

4. **Overcomplicating early**  
   Start with a simple BM25 + LLM pipeline; only add hybrid retrieval or agents if metrics justify it.

5. **No evaluation loop**  
   Without measurement and feedback, you won’t know what actually improved.

### 12.2 Best practices

- Start small: in‑memory store + BM25 + small LLM
- Add