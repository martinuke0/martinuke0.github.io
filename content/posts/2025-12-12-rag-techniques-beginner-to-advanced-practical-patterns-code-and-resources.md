---
title: "RAG Techniques, Beginner to Advanced: Practical Patterns, Code, and Resources"
date: "2025-12-12T13:52:29.669"
draft: false
tags: ["RAG", "LLM", "Vector Search", "NLP", "MLOps"]
---

## Introduction

Retrieval-Augmented Generation (RAG) pairs a retriever (to fetch relevant context) with a generator (an LLM) to produce accurate, grounded answers. This pattern reduces hallucinations, lowers inference costs by offloading knowledge into a searchable store, and makes updating knowledge as simple as adding or editing documents.

In this guide, we’ll move from beginner-friendly RAG to advanced techniques, with practical code examples along the way. We’ll cover chunking, embeddings, vector stores, hybrid retrieval, reranking, query rewriting, multi-hop reasoning, GraphRAG, production considerations, and evaluation. A final resources chapter includes links to papers, libraries, and tools.

> Note: Examples use open-source models to keep things reproducible. You can swap in managed LLMs or enterprise vector databases where appropriate.

---

## Table of Contents

- [Core Concepts and Terminology](#core-concepts-and-terminology)
- [Beginner: Build a Minimal RAG Pipeline](#beginner-build-a-minimal-rag-pipeline)
  - [Install and Prepare](#install-and-prepare)
  - [Index Documents](#index-documents)
  - [Retrieve + Generate](#retrieve--generate)
- [Intermediate Techniques](#intermediate-techniques)
  - [Chunking and Overlap](#chunking-and-overlap)
  - [Citations and Prompt Templates](#citations-and-prompt-templates)
  - [Metadata Filtering](#metadata-filtering)
  - [Reranking](#reranking)
  - [Hybrid Retrieval (Sparse + Dense)](#hybrid-retrieval-sparse--dense)
  - [Query Expansion (HyDE, Multi-Query)](#query-expansion-hyde-multi-query)
  - [Evaluation and Observability](#evaluation-and-observability)
  - [Latency and Cost Optimizations](#latency-and-cost-optimizations)
- [Advanced Techniques](#advanced-techniques)
  - [Multi-Hop Retrieval and Decomposition](#multi-hop-retrieval-and-decomposition)
  - [GraphRAG and Knowledge Graphs](#graphrag-and-knowledge-graphs)
  - [Multi-Vector and Learned Retrievers](#multi-vector-and-learned-retrievers)
  - [Context Optimization and Compression](#context-optimization-and-compression)
  - [Agentic RAG and Tool Use](#agentic-rag-and-tool-use)
  - [Safety and Grounding Guarantees](#safety-and-grounding-guarantees)
- [Production Considerations](#production-considerations)
- [End-to-End Example: Hybrid RAG with Reranking and Citations](#end-to-end-example-hybrid-rag-with-reranking-and-citations)
- [Debugging Checklist](#debugging-checklist)
- [Conclusion](#conclusion)
- [Resources](#resources)

---

## Core Concepts and Terminology

- Retriever: Finds relevant passages from a corpus.
  - Dense retrieval: Embeddings + vector search (FAISS, Chroma, Milvus, Weaviate, Elasticsearch vectors).
  - Sparse retrieval: BM25/TF-IDF (lexical match like Elasticsearch/OpenSearch).
- Generator: LLM that reads the retrieved context and answers.
- Embeddings: Vector representations of text, e.g., sentence-transformers, e5, bge.
- Chunking: Splitting documents into passages (e.g., 400–1000 tokens) with overlap to preserve context.
- Reranker: Cross-encoder (e.g., monoT5, bge-reranker) that re-orders retrieved passages for better precision.
- Hybrid retrieval: Combine sparse and dense results to improve recall/precision.
- RAG loop: Query → Retrieve → Rerank (optional) → Prompt LLM with top-k passages → Generate answer with citations.

---

## Beginner: Build a Minimal RAG Pipeline

This minimal setup uses:
- sentence-transformers for embeddings
- FAISS for vector search
- rank-bm25 (optional later) for lexical retrieval
- transformers (Flan-T5) to demonstrate generation

> You can replace the LLM with your provider of choice (OpenAI, Azure OpenAI, Anthropic, local models).

### Install and Prepare

```bash
pip install sentence-transformers faiss-cpu transformers accelerate rank-bm25 numpy
```

### Index Documents

```python
# minimal_rag_index.py
from sentence_transformers import SentenceTransformer
import faiss, numpy as np

# Example corpus
docs = [
    {"id": "1", "title": "RAG Overview", "text": "RAG combines retrieval with generation to ground answers."},
    {"id": "2", "title": "Embeddings", "text": "Dense embeddings map text to vectors for similarity search."},
    {"id": "3", "title": "BM25", "text": "Sparse retrieval like BM25 uses term frequency and inverse document frequency."},
    {"id": "4", "title": "Chunking", "text": "Chunk size and overlap impact recall and answer faithfulness."},
]

# Model and embeddings
emb_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
corpus_texts = [d["title"] + " — " + d["text"] for d in docs]
embs = emb_model.encode(corpus_texts, normalize_embeddings=True)
embs = np.array(embs, dtype="float32")

# Build FAISS index
dim = embs.shape[1]
index = faiss.IndexFlatIP(dim)  # inner product for cosine if normalized
index.add(embs)

# Persist artifacts (simple demo; consider a proper vector DB in production)
faiss.write_index(index, "demo.index")
import pickle
with open("docs.pkl", "wb") as f:
    pickle.dump(docs, f)
```

### Retrieve + Generate

```python
# minimal_rag_query.py
import faiss, pickle, numpy as np
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# Load artifacts
index = faiss.read_index("demo.index")
with open("docs.pkl", "rb") as f:
    docs = pickle.load(f)

# Load models
emb_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
tok = AutoTokenizer.from_pretrained("google/flan-t5-small")
llm = AutoModelForSeq2SeqLM.from_pretrained("google/flan-t5-small")

def retrieve(query, k=3):
    q = emb_model.encode([query], normalize_embeddings=True).astype("float32")
    scores, idxs = index.search(q, k)
    results = []
    for i, score in zip(idxs[0], scores[0]):
        d = docs[i]
        results.append({"doc": d, "score": float(score)})
    return results

def build_prompt(query, contexts):
    context_text = "\n\n".join(
        [f"[{i+1}] {c['doc']['title']}: {c['doc']['text']}" for i, c in enumerate(contexts)]
    )
    return f"""Use the context to answer the question. Cite sources in brackets like [1], [2].
Context:
{context_text}

Question: {query}
Answer:"""

def generate(prompt, max_tokens=256):
    inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=1024)
    out = llm.generate(**inputs, max_new_tokens=max_tokens)
    return tok.decode(out[0], skip_special_tokens=True)

if __name__ == "__main__":
    query = "What is RAG and how does it help reduce hallucinations?"
    topk = retrieve(query, k=3)
    prompt = build_prompt(query, topk)
    answer = generate(prompt)
    print("Answer:\n", answer)
```

This is a fully working minimal RAG loop. Accuracy will improve with better embedding models, chunking strategies, and reranking.

---

## Intermediate Techniques

### Chunking and Overlap

- Fixed-size chunks (e.g., 500–800 tokens) with 10–20% overlap balance recall and duplication.
- Semantic chunking: split by headings/sections, or via sentence boundaries to preserve meaning.
- Section-aware chunking: keep tables/code blocks intact to avoid orphaned context.

```python
def chunk_by_tokens(text, tokenizer, max_tokens=500, overlap=50):
    tokens = tokenizer.encode(text)
    chunks = []
    for start in range(0, len(tokens), max_tokens - overlap):
        piece = tokens[start:start + max_tokens]
        chunks.append(tokenizer.decode(piece))
    return chunks
```

### Citations and Prompt Templates

- Include identifiers and URLs in the prompt to encourage citations.
- Constrain the LLM to use only provided context.

```text
You are a helpful assistant. Only use the context. If the answer is not in the context, say "I don't know."
Return a JSON with: answer, citations (doc_id list).
```

### Metadata Filtering

Tag chunks with metadata like source, date, author, product line, region. Use filters at retrieval time to narrow the search.

Example metadata per chunk:
```json
{
  "id": "doc_42_chunk_3",
  "source": "handbook.pdf",
  "section": "onboarding",
  "created_at": "2023-11-12",
  "tags": ["policy", "hr"]
}
```

### Reranking

After initial retrieval, apply a cross-encoder to re-score passages with the query for better precision@k.

```python
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")  # fast, decent
pairs = [(query, r["doc"]["text"]) for r in topk]
scores = reranker.predict(pairs)
for r, s in zip(topk, scores):
    r["rerank_score"] = float(s)
topk = sorted(topk, key=lambda x: x["rerank_score"], reverse=True)[:3]
```

### Hybrid Retrieval (Sparse + Dense)

Combine BM25 (lexical) with dense vectors for robustness.

```python
from rank_bm25 import BM25Okapi

corpus = [d["text"] for d in docs]
bm25 = BM25Okapi([c.split() for c in corpus])

def hybrid_retrieve(query, k=5):
    # Dense
    qv = emb_model.encode([query], normalize_embeddings=True).astype("float32")
    dscores, didxs = index.search(qv, k)
    dense = [{"id": int(i), "score": float(s), "type": "dense"} for i, s in zip(didxs[0], dscores[0])]

    # Sparse
    sparse_scores = bm25.get_scores(query.split())
    sparse = [{"id": i, "score": float(s), "type": "sparse"} for i, s in enumerate(sparse_scores)]
    sparse = sorted(sparse, key=lambda x: x["score"], reverse=True)[:k]

    # Reciprocal Rank Fusion (RRF)
    def rrf(rank): return 1.0 / (60.0 + rank)  # k=60 typical
    candidates = {}
    for rank, d in enumerate(sorted(dense, key=lambda x: x["score"], reverse=True)):
        candidates.setdefault(d["id"], 0)
        candidates[d["id"]] += rrf(rank)
    for rank, s in enumerate(sparse):
        candidates.setdefault(s["id"], 0)
        candidates[s["id"]] += rrf(rank)

    merged = [{"doc": docs[i], "rrf": score} for i, score in candidates.items()]
    return sorted(merged, key=lambda x: x["rrf"], reverse=True)[:k]
```

### Query Expansion (HyDE, Multi-Query)

- HyDE: Have an LLM draft a hypothetical answer, embed it, retrieve with that embedding.
- Multi-Query: Generate paraphrases of the user question, retrieve for each, then union results.

```python
def multi_query_prompts(q):
    return [q,
            f"Paraphrase: {q} (technical)",
            f"Paraphrase: {q} (layperson)",
            f"Paraphrase: {q} (keywords only)"]

def multi_query_retrieve(q, k=3):
    all_results = {}
    for qq in multi_query_prompts(q):
        qv = emb_model.encode([qq], normalize_embeddings=True).astype("float32")
        scores, idxs = index.search(qv, k)
        for rank, (i, s) in enumerate(zip(idxs[0], scores[0])):
            all_results.setdefault(int(i), 0)
            all_results[int(i)] += 1.0 / (60 + rank)
    merged = [{"doc": docs[i], "score": s} for i, s in all_results.items()]
    return sorted(merged, key=lambda x: x["score"], reverse=True)[:k]
```

### Evaluation and Observability

- Document-level: Recall@k, Precision@k, nDCG, MRR (using known relevant passages).
- Answer-level: Faithfulness (is each claim supported?), relevance, completeness.
- Tooling:
  - Ragas: question-answer-grounding metrics.
  - TruLens, DeepEval: guardrail checks, scoring pipelines.
  - Human-in-the-loop spot checks with templated rubrics.

> Caution: LLM-as-judge can be biased; calibrate with human labels and hold-out sets.

### Latency and Cost Optimizations

- Cache embeddings and retrieval results.
- Precompute document embeddings offline; batch encode.
- Lower k after reranking (e.g., retrieve 20, rerank to top 5).
- Use smaller rerankers for interactive workloads; upscale in batch.
- Compress contexts (see context optimization) to reduce tokens.

---

## Advanced Techniques

### Multi-Hop Retrieval and Decomposition

Complex questions may require chaining facts across multiple documents.

Patterns:
- Decomposition: Use the LLM to break the query into sub-questions, retrieve for each, then synthesize.
- ReAct: Interleave reasoning and retrieval (“Thought → Action: search → Observation”).

```python
decompose_prompt = """Break the question into 2-4 sub-questions to answer sequentially.
Question: {q}
Return as a numbered list only."""
```

Iterate: for each sub-question, retrieve, summarize, feed forward.

### GraphRAG and Knowledge Graphs

- Build a graph of entities and relations from your corpus (NER + relation extraction).
- Retrieve nodes/edges relevant to the query (e.g., neighborhood expansion).
- Provide the LLM with graph triples alongside text passages.

Benefits: better multi-hop, disambiguation, and provenance.

### Multi-Vector and Learned Retrievers

- ColBERT-style late interaction: multiple vectors per passage enable fine-grained matching.
- SPLADE and other sparse learned retrievers improve lexical matching with learned expansions.
- Domain adaptation: fine-tune bi-encoders (e.g., Contriever, e5) on in-domain pairs with contrastive loss.

> When you own data and scale, learned retrievers can outperform general-purpose embeddings.

### Context Optimization and Compression

- Passage selection: dynamic windowing to include only the most relevant sentences from a chunk.
- Map-reduce summarization: summarize many chunks into compact notes before answering.
- Selective citation: include minimal snippets with line numbers to anchor claims.

```python
def compress_passage(passage, query, llm_call):
    # Ask LLM to extract 3-5 sentences relevant to the query
    prompt = f"Extract only sentences relevant to: {query}\nText:\n{passage}\nOutput:"
    return llm_call(prompt)
```

### Agentic RAG and Tool Use

- Add tools: web search, code execution, database queries.
- Routing: classify queries to the right retriever or knowledge domain.
- Iterative retrieval: the agent requests more documents if uncertainty is high.

### Safety and Grounding Guarantees

- Enforce “cite-before-say”: require evidence snippets for each claim.
- Use consistency checks: self-consistency over multiple retrieval seeds.
- Red-team prompts; set content filters on both query and generation.
- Post-hoc verification: compare emitted facts to retrieved text (string/semantic match).

---

## Production Considerations

- Data freshness: implement continuous ingestion pipelines, deduplication, and re-indexing.
- Sharding and scaling: partition indexes by tenant or topic; use ANN indexes with IVF/HNSW.
- Metadata governance: consistent schemas, PII handling, role-based access filters at retrieval time.
- Monitoring:
  - Query drift (topic changes)
  - Retrieval quality (Recall@k)
  - Answer quality (faithfulness, user feedback)
  - Latency SLOs and cost per question
- A/B testing: measure business outcomes, not just offline metrics.
- Versioning: snapshot indexes and prompts; keep reproducible builds.

---

## End-to-End Example: Hybrid RAG with Reranking and Citations

This example ties together hybrid retrieval, reranking, and citation-enforced generation.

```python
# hybrid_rag_end_to_end.py
import pickle, faiss, numpy as np
from sentence_transformers import SentenceTransformer, CrossEncoder
from rank_bm25 import BM25Okapi
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# Load or prepare docs/embeddings/index as before
with open("docs.pkl", "rb") as f:
    docs = pickle.load(f)
index = faiss.read_index("demo.index")
emb_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# Sparse
bm25 = BM25Okapi([d["text"].split() for d in docs])

# Reranker
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

# Generator
tok = AutoTokenizer.from_pretrained("google/flan-t5-base")
llm = AutoModelForSeq2SeqLM.from_pretrained("google/flan-t5-base")

def rrf(rank): return 1.0 / (60.0 + rank)

def retrieve_hybrid(query, k_dense=15, k_sparse=15, k_final=8):
    # Dense
    qv = emb_model.encode([query], normalize_embeddings=True).astype("float32")
    dscores, didxs = index.search(qv, k_dense)
    dense = [(int(i), float(s)) for i, s in zip(didxs[0], dscores[0])]

    # Sparse
    sparse_scores = bm25.get_scores(query.split())
    sparse_ranked = sorted(list(enumerate(sparse_scores)), key=lambda x: x[1], reverse=True)[:k_sparse]

    # RRF merge
    scores = {}
    for rank, (i, _) in enumerate(sorted(dense, key=lambda x: x[1], reverse=True)):
        scores.setdefault(i, 0); scores[i] += rrf(rank)
    for rank, (i, _) in enumerate(sparse_ranked):
        scores.setdefault(i, 0); scores[i] += rrf(rank)

    candidates = [{"idx": i, "rrf": s, "text": docs[i]["text"], "title": docs[i]["title"], "id": docs[i]["id"]}
                  for i, s in scores.items()]
    # Rerank with cross-encoder
    pairs = [(query, c["text"]) for c in candidates]
    ce_scores = reranker.predict(pairs)
    for c, sc in zip(candidates, ce_scores):
        c["rerank"] = float(sc)
    topk = sorted(candidates, key=lambda x: x["rerank"], reverse=True)[:k_final]
    return topk

def build_prompt(query, contexts):
    ctx = "\n\n".join([f"[{i+1}] ({c['id']}) {c['title']}: {c['text']}" for i, c in enumerate(contexts)])
    return f"""You answer only with the provided context and must cite sources like [1], [2].
If the answer is not present, say "I don't know."

Context:
{ctx}

Question: {query}
Answer (with citations):"""

def answer(query):
    contexts = retrieve_hybrid(query)
    prompt = build_prompt(query, contexts)
    inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=2048)
    out = llm.generate(**inputs, max_new_tokens=256)
    text = tok.decode(out[0], skip_special_tokens=True)
    return text, contexts

if __name__ == "__main__":
    q = "Compare BM25 and dense embeddings in RAG and when to use hybrid retrieval."
    ans, ctxs = answer(q)
    print(ans)
    print("\nSources:")
    for i, c in enumerate(ctxs):
        print(f"[{i+1}] {c['id']} — {c['title']}")
```

What this adds:
- Hybrid retrieval improves recall.
- Reranking improves precision.
- Prompt enforces citations and abstention.

---

## Debugging Checklist

- Is chunking too small/large? Try 300–800 tokens with overlap 10–20%.
- Are embeddings appropriate for your domain/language? Test a few (e.g., e5, bge, MiniLM).
- Is top-k too low? Increase k then rerank down.
- Are results dominated by one document? Deduplicate and diversify sources.
- Are answers hallucinating? Tighten the prompt, require citations, add “I don’t know.”
- Is latency high? Cache, batch, reduce k, use faster reranker.
- Are you missing recent info? Rebuild the index and verify ingestion.
- Are filters excluding relevant docs? Log applied metadata filters.

---

## Conclusion

RAG is a flexible, production-ready pattern for grounding LLMs in your data. Start simple: good chunking, a solid embedding model, and a basic vector index. Then layer in improvements where they matter most: hybrid retrieval to boost recall, rerankers for precision, query expansion for robustness, and evaluation to quantify gains. For complex reasoning, explore decomposition, multi-hop, and graph-based retrieval. Finally, harden your system with observability, safety, and cost controls.

With the techniques and examples in this guide, you can build RAG systems that are accurate, scalable, and maintainable—from prototype to production.

---

## Resources

Core papers and concepts:
- Retrieval-Augmented Generation: Lewis et al., 2020 — https://arxiv.org/abs/2005.11401
- ReAct: Reasoning and Acting — https://arxiv.org/abs/2210.03629
- HyDE: Hypothetical Document Embeddings — https://arxiv.org/abs/2212.10496
- ColBERT: Late Interaction — https://arxiv.org/abs/2004.12832
- BEIR Benchmark — https://arxiv.org/abs/2104.08663
- SPLADE (Sparse Lexical and Expansion) — https://arxiv.org/abs/2107.05720
- GraphRAG (Microsoft Research summary) — https://arxiv.org/abs/2404.16130

Libraries and frameworks:
- sentence-transformers — https://www.sbert.net
- FAISS — https://github.com/facebookresearch/faiss
- Chroma — https://www.trychroma.com
- Milvus — https://milvus.io
- Weaviate — https://weaviate.io
- Elasticsearch dense and BM25 — https://www.elastic.co/guide/en/elasticsearch/reference/current/dense-vector.html
- LangChain — https://python.langchain.com
- LlamaIndex — https://www.llamaindex.ai
- Haystack — https://haystack.deepset.ai
- rank-bm25 — https://github.com/dorianbrown/rank_bm25
- CrossEncoder rerankers — https://www.sbert.net/examples/applications/cross-encoder/README.html
- bge-reranker models — https://huggingface.co/BAAI

Evaluation and observability:
- Ragas — https://github.com/explodinggradients/ragas
- TruLens — https://www.trulens.org
- DeepEval — https://github.com/confident-ai/deepeval

Design and best practices:
- Pinecone blog on chunking strategies — https://www.pinecone.io/learn/chunking-strategies
- Weaviate RAG patterns — https://weaviate.io/developers/weaviate
- OpenAI Retrieval Cookbook — https://github.com/openai/openai-cookbook/tree/main/examples/vector_databases

Model hubs:
- Hugging Face models (e5, bge, MiniLM) — https://huggingface.co/models
- T5/Flan-T5 — https://huggingface.co/google/flan-t5-base

> Keep these bookmarked; they’re frequently updated with new techniques and model families.