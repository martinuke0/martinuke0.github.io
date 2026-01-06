---
title: "System Design for LLMs: A Zero-to-Hero Guide"
date: "2026-01-06T08:49:32.391"
draft: false
tags: ["system design", "llm", "architecture", "rag", "ai engineering"]
---

## Introduction

Designing systems around large language models (LLMs) is not just about calling an API. Once you go beyond toy demos, you face questions like:

- How do I keep latency under control as usage grows?
- How do I manage costs when token usage explodes?
- How do I make results reliable and safe enough for production?
- How do I deal with context limits, memory, and personalization?
- How do I choose between hosted APIs and self-hosting?

This post is a **zero-to-hero** guide to **system design for LLM-powered applications**. It assumes you’re comfortable with web backends / APIs, but not necessarily a deep learning expert.

You’ll learn:

- Core concepts: tokens, context, embeddings, RAG
- How to design a minimal but solid LLM system
- How to evolve it into a scalable, reliable architecture
- Key patterns (RAG, caching, agents, workflows)
- How to think about latency, cost, safety, and observability
- Where to go deeper: papers, tools, and learning resources

Where relevant, you’ll see simplified code examples and links to concrete tools.

---

## 1. Foundations: Mental Model & Requirements

Before drawing any architecture, you need a clear mental model of what an LLM actually is from a system design perspective.

### 1.1 LLM as a function

Abstractly, treat an LLM as a function:

```text
output_tokens = LLM(prompt_tokens, parameters)
```

Where:

- `prompt_tokens` = tokenized input text (user message + system instructions + context)
- `parameters` = temperature, max tokens, system prompt, stop sequences, tools, etc.
- `output_tokens` = generated token stream

Characteristics:

- **Stateless per request** (unless you add state externally)
- **Heavy compute**: Inference is expensive compared to typical CRUD workloads
- **Probabilistic**: Same input can produce different outputs

All system design patterns we’ll discuss are essentially ways to manage:

- **State** (conversations, memory, indexes)
- **Compute** (latency, throughput, capacity)
- **Quality & safety** (guardrails, retrieval, evaluation)

### 1.2 Common functional requirements

LLM systems often need to:

- Answer questions over private data
- Generate or transform content (docs, code, emails)
- Assist in workflows and tools (agents calling APIs)
- Support multi-turn conversations with memory

Each use case changes how you design:

- Do you need **RAG** (retrieval-augmented generation)?
- Do you need **agents** (tool calling, multi-step workflows)?
- Do you need **fine-tuning** or can you rely on prompts + RAG?

### 1.3 Non-functional requirements

Your architecture will be shaped by:

- **Latency**
  - Interactive chat: P95 < 2–4 seconds; stream tokens as soon as possible
  - Backend workflows: maybe P95 < 10–30 seconds is fine
- **Throughput**
  - QPS (queries per second)
  - Token/sec (input and output)
- **Cost**
  - Per-request cost budget
  - Monthly budget ceilings
- **Reliability**
  - Error rate, timeouts, fallbacks
  - SLIs/SLOs (availability, correctness)
- **Security & privacy**
  - PII, data residency, compliance needs
- **Maintainability**
  - Ability to swap models / providers
  - Adding new workflows without rewrites

Keep these in mind as we design from basic to advanced.

---

## 2. Core Building Blocks for LLM Systems

### 2.1 Hosted APIs vs self-hosted models

**Option 1: Hosted APIs (OpenAI, Anthropic, Gemini, etc.)**

Pros:
- No infra or GPU management
- Fast iteration, strong models
- Built-in safety tools and monitoring

Cons:
- Ongoing usage cost
- Latency and data residency dependency on provider
- Limited control over model internals

Useful for: startups, internal tools, most early products.

**Option 2: Self-hosted open-weight models (Llama, Mistral, etc.)**

Pros:
- Control over data, deployment, and latency
- Possible lower marginal cost at scale
- Customization (fine-tuning, specialized formats)

Cons:
- Need GPU infra, scaling, optimization expertise
- Model quality may lag strongest proprietary models (though gap is shrinking)

Useful for: privacy-sensitive use cases, cost-sensitive high-volume workloads, on-prem.

You can also use **hybrid** setups: primary provider with a backup, plus some local models for specific tasks (e.g., small classifier or embedder).

### 2.2 Tokens, context windows, and limits

Key concepts:

- **Tokens** are units of text roughly 3–4 characters (for English).
- **Context window** = max tokens per request (input + output).
- Example: a “128k token context” can handle about 100k input + 28k output.

Implications:

- Long documents must be **chunked** to fit context.
- History in chat must be **summarized** or truncated.
- Token usage directly affects:
  - Latency (more tokens → slower)
  - Cost (more tokens → more $)
  - Quality (too little context → hallucinations)

Useful tools:

- [tiktoken](https://github.com/openai/tiktoken) (OpenAI tokenizer)
- [tokenizers](https://github.com/huggingface/tokenizers) (Hugging Face)

### 2.3 Embeddings and vector stores

An **embedding** is a vector representation of text capturing semantic meaning.

Pipeline:

```text
text -> embedding_model -> vector (e.g., 768-dim) -> store in vector DB
```

Typical uses:

- **Semantic search**: find similar passages for a query
- **RAG**: retrieve relevant context to feed into the LLM
- **Clustering, deduplication, recommendations**

Vector DB options:

- Managed: [Pinecone](https://www.pinecone.io/), [Weaviate Cloud](https://weaviate.io/), [Qdrant Cloud](https://qdrant.tech/)
- Self-hosted: [Qdrant](https://github.com/qdrant/qdrant), [Weaviate](https://github.com/weaviate/weaviate), [FAISS](https://github.com/facebookresearch/faiss)

### 2.4 Inference engines and model formats (self-hosting)

If you self-host, you’ll encounter:

- **Inference engines**
  - [vLLM](https://github.com/vllm-project/vllm): high-throughput LLM serving
  - [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM): NVIDIA-optimized
  - [text-generation-inference](https://github.com/huggingface/text-generation-inference)

- **Formats & precision**
  - `fp16` / `bf16`: standard for high-quality inference
  - `int8`, `int4`: quantized for smaller memory, faster inference, some quality tradeoff
  - `GGUF`: CPU-friendly format for [llama.cpp](https://github.com/ggerganov/llama.cpp)

System design decisions:

- Do you centralize GPUs or deploy near each region?
- Do you share GPU nodes across models or dedicate per model?
- Do you batch requests for throughput or prioritize latency?

We’ll return to these in the scaling section.

---

## 3. A Minimal LLM System: Single-Node Architecture

Start simple. A solid MVP architecture looks like:

```text
Client (web/mobile)
   |
   v
API Gateway / Load Balancer
   |
   v
App Server (FastAPI / Node / etc.)
   |
   |---> LLM Provider (OpenAI / Anthropic / etc.)
   |
   --> DB (for users, messages, logs)
```

Characteristics:

- Single app server (can auto-scale later)
- No RAG yet—direct prompts only
- All state (users, messages) in a relational DB or similar

### 3.1 Example: Chat API with OpenAI + FastAPI

```python
# app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os

app = FastAPI()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

class ChatRequest(BaseModel):
    user_id: str
    messages: list[dict]  # [{'role': 'user'|'assistant'|'system', 'content': '...'}]

@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=req.messages,
            max_tokens=512,
            temperature=0.7,
            stream=False,
        )
        return {
            "reply": completion.choices[0].message.content,
            "usage": completion.usage.model_dump() if completion.usage else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

Then you add:

- **User authentication** (JWT, session cookies)
- **Rate limiting** per user or API key
- **Logging** of prompts & responses (with redaction if you handle PII)

### 3.2 Storing conversation history

You need to store messages to maintain context across turns.

Option A: Store raw message history in DB, and send **full history** each time until you hit context limits.

Option B: Implement **conversation summarization**:

- Store all messages
- Generate a running summary when history gets long
- Use:

```text
[system instructions] + [summary] + [last N exchanges]
```

instead of full raw history.

Example table schema (simplified):

```sql
CREATE TABLE conversations (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    title TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE messages (
    id UUID PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id),
    role TEXT CHECK (role IN ('system', 'user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);
```

---

## 4. Systems with Retrieval-Augmented Generation (RAG)

Most serious applications need the model to answer questions **based on your data**, not just its pretraining.

### 4.1 High-level RAG architecture

```text
             ┌─────────────────────┐
             │  Data Sources        │
             │  (docs, db, APIs)    │
             └────────┬────────────┘
                      │
                [Ingestion & ETL]
                      │
                      v
            ┌─────────────────────┐
            │ Chunking & Cleaning │
            └────────┬────────────┘
                      │
                      v
            ┌─────────────────────┐
            │ Embeddings Model    │
            └────────┬────────────┘
                      │
                      v
            ┌─────────────────────┐
            │ Vector Store        │
            └────────┬────────────┘
                      │
 Query → Embeddings → │ → Top-K Chunks → Prompt Assembly → LLM → Answer
```

Key phases:

1. **Ingestion**: fetch and normalize data (docs, HTML, DB records, PDFs)
2. **Chunking**: split into manageable chunks with overlap
3. **Embedding**: convert chunks to vectors
4. **Indexing**: store vectors in a vector DB
5. **Retrieval**: for each query, embed and find top-K similar chunks
6. **Generation**: build a prompt with retrieved context and call LLM

### 4.2 Designing the ingestion and chunking pipeline

Questions to answer:

- How often does the data change?
  - Static docs: nightly batch is fine
  - Frequently changing: streaming or near real-time ingestion
- What chunk size and overlap?
  - Common: 256–1024 tokens per chunk with 10–20% overlap
  - Tradeoff: smaller chunks → more precise matches but more pieces to assemble

Example chunking/linking with Python:

```python
def chunk_text(text: str, max_tokens: int = 512, overlap: int = 64) -> list[str]:
    # Simplified character-based chunking. In practice, use tokenizer-based.
    step = max_tokens - overlap
    chunks = []
    for i in range(0, len(text), step):
        chunk = text[i:i + max_tokens]
        chunks.append(chunk)
    return chunks
```

Libraries that can help:

- [LangChain text splitters](https://python.langchain.com/docs/modules/data_connection/document_transformers/)
- [LlamaIndex node parsers](https://docs.llamaindex.ai/en/stable/module_guides/loading/node_parsers/)

### 4.3 Example: Building a RAG query pipeline

Assume:

- Embeddings model: `text-embedding-3-large` (OpenAI)
- Vector DB: Qdrant
- LLM: `gpt-4.1-mini` or similar

```python
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
import uuid
import os

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
qdrant = QdrantClient(url="http://localhost:6333")

COLLECTION = "docs"

def embed(texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(
        model="text-embedding-3-large",
        input=texts,
    )
    return [item.embedding for item in resp.data]

def index_documents(docs: list[dict]):
    """
    docs: [{'id': 'doc1', 'text': '...'}, ...]
    """
    texts = [d["text"] for d in docs]
    vectors = embed(texts)
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vec,
            payload={"doc_id": doc["id"], "text": doc["text"]},
        )
        for vec, doc in zip(vectors, docs)
    ]
    qdrant.upsert(collection_name=COLLECTION, points=points)

def retrieve(query: str, top_k: int = 5) -> list[str]:
    query_vec = embed([query])[0]
    res = qdrant.search(
        collection_name=COLLECTION,
        query_vector=query_vec,
        limit=top_k,
    )
    return [hit.payload["text"] for hit in res]

def answer_query(query: str) -> str:
    contexts = retrieve(query)
    system_prompt = (
        "You are a helpful assistant. Answer using only the provided context. "
        "If you are unsure or the answer is not in the context, say so explicitly."
    )
    context_block = "\n\n---\n\n".join(contexts)
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"Context:\n{context_block}\n\nQuestion: {query}",
        },
    ]
    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
    )
    return completion.choices[0].message.content
```

### 4.4 RAG design choices that matter

- **Embedding model choice**
  - Larger models → better semantic matching, higher cost, slower
  - Consider: [OpenAI embeddings](https://platform.openai.com/docs/guides/embeddings),
    [Cohere embeddings](https://docs.cohere.com/docs/embeddings),
    [Jina embeddings](https://jina.ai/embeddings).

- **Indexing strategy**
  - Flat vs HNSW vs IVF (depends on DB)
  - Filtering by metadata (e.g., doc type, tenant)

- **Retrieval strategy**
  - Pure vector similarity
  - Hybrid (BM25 + embeddings)
  - Re-ranking (e.g., [Cohere Rerank](https://docs.cohere.com/docs/rerank),
    [OpenAI re-rank models when available], or local cross-encoders)

- **Prompting strategy**
  - Instruction to avoid hallucinations
  - Chain-of-thought or “let’s reason step by step” where needed
  - Cite sources explicitly (include doc IDs, URLs in payloads)

Resources to deepen RAG:

- [LangChain RAG guide](https://python.langchain.com/docs/use_cases/question_answering/)
- [LlamaIndex RAG patterns](https://docs.llamaindex.ai/en/stable/getting_started/concepts.html)
- [Pinecone RAG best practices](https://www.pinecone.io/learn/series/rag/)

---

## 5. Scaling from MVP to Production

As traffic grows, you need to handle:

- Higher QPS
- Spikier workloads
- New features and complex workflows
- Model and provider evolution

### 5.1 Stateless app servers

Keep your **application servers stateless**:

- Store user data, conversations, and documents in DBs
- For RAG, store embeddings in vector DB
- For longer workflows, state in DB or workflow engine

Then scale app servers horizontally:

- Kubernetes (GKE, EKS, AKS)
- Serverless (Cloud Run, Lambda, Fargate)

Example Kubernetes deployment (simplified):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: llm-app
  template:
    metadata:
      labels:
        app: llm-app
    spec:
      containers:
        - name: llm-app
          image: your-registry/llm-app:latest
          ports:
            - containerPort: 8000
          env:
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: openai-secrets
                  key: api-key
```

### 5.2 Rate limiting and backpressure

Protect yourself and your provider:

- **Rate limit per user / API key / IP**
  - E.g., using Redis + sliding window counters
- **Provider-side limits**
  - Enforce global concurrency and QPS so you don’t exceed provider quotas
- **Backpressure**
  - If queues grow too long, reject or defer requests with a clear message

Example conceptual pipeline:

```text
Client → API Gateway → Rate limiter → Queue → Worker → LLM API
```

For interactive chat, you usually call LLM synchronously; for bulk jobs, you push tasks into a queue (e.g., RabbitMQ, SQS, Kafka) processed by workers.

### 5.3 Multi-model, multi-provider routing

Avoid hard-coding a single model everywhere.

Introduce an **abstraction layer**:

```text
Your code → ModelRouter → Providers (OpenAI, Anthropic, local vLLM, etc.)
```

Capabilities:

- Route by:
  - Use case (chat, classification, embedding)
  - Tenant (some tenants need on-prem only)
  - Cost/latency vs quality preferences
- Failover:
  - If provider A fails → fallback to provider B
- A/B testing:
  - Gradually rollout new models

You can roll your own or leverage tools like:

- [OpenAI-compatible proxies](https://github.com/xorbitsai/inference) for multi-backend
- [OpenRouter](https://openrouter.ai/) for unified API over many models
- [LiteLLM](https://github.com/BerriAI/litellm) as a model router/proxy

---

## 6. Latency & Throughput Optimization

Performance is critical for user experience and cost.

### 6.1 First, measure

Track:

- **End-to-end latency**
  - P50, P90, P95, P99
  - For different endpoints and workflows
- **Provider latency**
  - Time from sending request to first token and to final token
- **Token usage**
  - Input tokens, output tokens, total

Use a metrics system like:

- [Prometheus + Grafana](https://prometheus.io/)
- Cloud-native monitoring: CloudWatch, Stackdriver, Datadog, New Relic

### 6.2 Reduce token usage

Token usage is often your biggest lever for both latency and cost.

Techniques:

- **Prompt compression**
  - Drop unnecessary instructions
  - Use more concise schemas
- **Context truncation/summarization**
  - Summarize long history
  - Limit number of retrieved documents
- **Dynamic max tokens**
  - Don’t always request, say, 1024 tokens if you usually need 100

Example: dynamic `max_tokens` heuristic in Python:

```python
def estimate_max_tokens(user_query: str) -> int:
    # naive: shorter query → smaller expected answer
    if len(user_query) < 100:
        return 256
    elif len(user_query) < 500:
        return 512
    return 1024
```

### 6.3 Streaming responses

For interactive use, always enable **token streaming**:

- The model starts returning tokens as it generates them.
- Users see partial responses quickly, even if full completion takes several seconds.

OpenAI streaming example (Python):

```python
from openai import OpenAI
client = OpenAI()

stream = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[{"role": "user", "content": "Explain transformers in 3 sentences."}],
    stream=True,
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

On the frontend, update the UI as tokens arrive.

### 6.4 Caching strategies

Caching is crucial for cost and latency.

Types of caches:

1. **Request-level cache**
   - Key: full prompt (or normalized version)
   - Value: full response
   - Good for deterministic or low-temperature calls and repeated queries

2. **Partial prompt cache**
   - Cache intermediate results of expensive parts (e.g., summarizing a doc)
   - ID-based: e.g., `summary:doc_id:1234`

3. **Vector cache**
   - Cache previous query → embeddings → retrieval results
   - Avoid repeated embed calls for same input

Store caches in:

- Redis / Memcached for high-speed.
- Persistent DB (Postgres) for “expensive to compute” derived artifacts.

> Note: For safety, consider whether caching user-specific inputs could leak sensitive info across tenants. Key by user/tenant where appropriate.

### 6.5 Batch and parallel operations

For high-throughput or bulk jobs:

- **Batch embeddings**: embed multiple texts in a single API call.
- **Parallel LLM calls**: e.g., generating responses for many independent tasks concurrently (respecting rate limits).

Example: batch embeddings (OpenAI):

```python
texts = ["text1", "text2", "text3"]
resp = client.embeddings.create(
    model="text-embedding-3-large",
    input=texts,
)
embs = [item.embedding for item in resp.data]
```

Batching can dramatically improve throughput for self-hosted setups (via vLLM or TensorRT-LLM).

### 6.6 Advanced: speculative decoding and small models

For self-hosted:

- **Speculative decoding**: small “draft” model generates tokens; large model verifies a chunk at a time.
  - Implemented in some inference engines (vLLM, etc.)

For both hosted and self-hosted:

- Use **smaller, cheaper models** for:
  - Classification
  - Simple extraction
  - Pre-filtering or scoring
- Reserve larger models for:
  - Complex reasoning
  - User-facing answers

---

## 7. Reliability, Safety, and Monitoring

### 7.1 Error handling & fallbacks

LLM calls can fail due to:

- Network issues
- Provider outages
- Rate limit exceeded
- Timeouts on long generations

Approach:

- **Retry with backoff** for transient errors
- **Fallback strategies**:
  - Shorter prompt or lower max tokens
  - Simpler or smaller model
  - Different provider
  - Return a graceful message: “I’m having trouble; please try again.”

Design SLOs like:

- Availability: 99.9% of requests get a response within X seconds
- Error rate: < 0.1% of requests fail due to system errors

### 7.2 Guardrails and safety

LLMs can produce:

- Toxic or unsafe content
- Confidential info leakage
- Incorrect or misleading answers

Mitigation layers:

1. **Input validation**
   - Detect and block obvious malicious inputs (e.g., prompt-injection attempts, jailbreak patterns).
   - Check for PII if needed.

2. **Content moderation**
   - Use provider moderation APIs:
     - [OpenAI Moderation](https://platform.openai.com/docs/guides/moderation)
     - [Perspective API](https://perspectiveapi.com/)
   - Or local safety classifiers.

3. **Prompt design**
   - Clearly instruct model:
     - To refrain from answering beyond its context
     - To avoid giving financial, medical, or legal advice beyond safe bounds

4. **Post-generation filters**
   - Analyze outputs for policy violations
   - Block or redact pieces

Tools:

- [Guardrails AI](https://github.com/guardrails-ai/guardrails)
- [Rebuff](https://github.com/i-am-bee/Rebuff) for prompt injection defense
- [Llama Guard](https://ai.meta.com/research/publications/llama-guard/) (Meta’s safety model for moderation / filtering)

### 7.3 Observability and evaluation

Beyond standard observability (logs, metrics, traces), LLM systems need **LLM-specific evaluation**:

- **Offline evals**
  - Build a test set of prompts + expected outputs or scoring criteria
  - Use:
    - Human raters
    - Another LLM as a “judge” (with careful prompts)
  - Tools:
    - [DeepEval](https://github.com/confident-ai/deepeval)
    - [Helm](https://crfm.stanford.edu/helm/latest/)
    - [TruLens](https://github.com/truera/trulens)

- **Online evals**
  - Thumbs up/down from users
  - Report buttons (“Incorrect”, “Offensive”, “Not helpful”)
  - Feedback stored with prompts/responses for analysis

- **Key quality metrics**
  - Answer correctness / faithfulness to context (for RAG)
  - Factuality / hallucination rate
  - Coverage: did it cite all relevant docs?
  - Safety: toxicity / policy violation rate

Aim for a pipeline where you:

1. Log all prompts + responses (with redaction where required)
2. Regularly sample and evaluate
3. Use insights to refine prompts, retrieval, and model choices

---

## 8. Data, Personalization, and Memory

### 8.1 Short-term vs long-term memory

**Short-term memory**

- Conversation context within a single chat session
- Stored as messages or summary + recent turns
- Lives in the DB and is passed to the LLM

**Long-term memory**

- User profile: preferences, role, history
- Documents the user created or uploaded
- Long-running project context

Design patterns:

- Store user-specific memory in:
  - Relational DB (structured preferences)
  - Vector DB (semantic memories, notes, docs)
- Use **RAG** over user-specific memory:
  - Filter by `user_id` in vector DB metadata
- Add memory to prompt:
  - E.g., “The user prefers concise answers and works in finance.”

### 8.2 Personalization vs privacy

Be explicit about:

- What data you store
- How long you retain it
- How you use it for personalization

Best practices:

- Encrypt sensitive data at rest and in transit
- Avoid using user data to fine-tune global models without user consent
- Tenant isolation:
  - Separate indexes per tenant or strong metadata filters
  - Avoid cross-tenant retrieval

Regulation-aware design:

- For GDPR/CCPA:
  - Data deletion workflows
  - Data export / portability
- For HIPAA / financial data:
  - Consider on-prem or VPC-hosted models
  - Avoid sending PHI to external APIs unless you have BAA/agreements

---

## 9. System Design Patterns & Reference Architectures

### 9.1 LLM as an internal “model service”

Pattern:

```text
Upstream Services → Model API Service → Providers / Models
```

- **Model API Service**:
  - Uniform HTTP/gRPC API
  - Handles:
    - Provider-specific auth, rate limits
    - Request shaping, logging, metrics
    - A/B tests and routing

Pros:

- Centralizes ML infra
- Makes swapping models easier

Cons:

- Another service to maintain; might become a bottleneck if not scaled well

### 9.2 RAG microservice

Pattern:

```text
App / Frontend → RAG Service → Vector DB + LLM
```

- RAG service encapsulates:
  - Query preprocessing
  - Retrieval & re-ranking
  - Prompt construction
  - Call to LLM
- Returns:
  - Answer
  - Supporting documents

Good for:

- Search/chat across knowledge bases
- Internal “AI assistant” for docs

### 9.3 Agentic workflows and tool calling

Agents go beyond single prompt/response calls; they:

- Plan multi-step tasks
- Call tools (APIs, DBs, search)
- Use intermediate results to refine next actions

Architecture:

```text
Client → Orchestrator / Agent Runtime → Tools/Services + LLM
```

Tools / frameworks:

- [LangGraph](https://langchain-ai.github.io/langgraph/) (graph-based agents)
- [CrewAI](https://github.com/joaomdmoura/crewAI)
- [Semantic Kernel](https://github.com/microsoft/semantic-kernel)

Design considerations:

- Keep tools **idempotent** or handle retries carefully.
- Track **tool call logs** and intermediate states.
- Put **hard limits** on recursion depth and number of tool invocations per request.

### 9.4 Multi-tenant SaaS pattern

If you build an LLM-based SaaS:

- Each tenant has:
  - Separate data (DB schemas, row-level security, or separate DB)
  - Separate RAG indexes (logical collections or metadata-based isolation)
- **Usage metering** per tenant:
  - Track tokens, requests, errors
  - Bill or rate-limit accordingly

Architecture snippet:

```text
Tenant Admin → Admin Panel → Config DB
Tenant Users → App → Multi-tenant DB + Multi-tenant Vector DB + Model Router
```

Use robust auth and authorization:

- OIDC, JWT
- Row-level security (e.g., in Postgres)
- Vector DB with per-tenant filters

---

## 10. Cost Management

Uncontrolled token usage and GPU time can surprise you.

### 10.1 Basic cost model

For hosted APIs:

```text
Cost per request ≈ (input_tokens / 1K) * input_price_per_1K
                 + (output_tokens / 1K) * output_price_per_1K
                 + embeddings_costs + other ops
```

For self-hosted:

```text
Monthly GPU cost = (#GPUs) * (GPU_hourly_price) * 24 * 30
Per-request cost ≈ (GPU_time_per_request / total_GPU_time_month) * monthly_GPU_cost
```

### 10.2 Cost control techniques

- **Token minimization**
  - As discussed: shorter prompts, dynamic max tokens, less context
- **Model tiering**
  - Use cheaper models where you can; reserve expensive ones for critical paths
