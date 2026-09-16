

---
title: "Build an End-to-End RAG System for Your Portfolio"
date: "2026-09-16T09:01:13.414"
draft: false
tags: ["RAG", "Python", "FastAPI", "LangChain", "OpenAI", "VectorDB"]
description: "A practical guide to building a retrieval-augmented generation system with FastAPI, LangChain, and OpenAI, perfect for showcasing real systems skills to hiring managers."
summary: "Learn to build a production-style RAG pipeline that demonstrates end-to-end systems engineering, from data ingestion to API serving."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-16-build-an-end-to-end-rag-system-for-your-portfolio.svg"
  alt: "A dashboard showing a RAG system answering questions"
  caption: ""
  relative: false
---

> **TL;DR** — This guide walks you through building a full RAG pipeline: ingest documents, embed them with OpenAI, store them in a vector database, and serve the results via a FastAPI endpoint. The project demonstrates data engineering, API design, and LLM integration—skills that stand out on any systems‑oriented CV.

In a market where “AI” is a checkbox, a concrete, end‑to‑end retrieval‑augmented generation (RAG) system proves you can ship a real product, not just a demo. Below you’ll find a step‑by‑step implementation that you can run on a laptop, extend to production, and list on your résumé.

## Why This Project Stands Out on a CV

- **End‑to‑end ownership** – you handle ingestion, embedding, storage, retrieval, and serving, mirroring a full‑stack engineer’s responsibilities.
- **Modern stack** – FastAPI, LangChain, OpenAI embeddings, and a vector DB (Chroma or Pinecone) are the same tools used in production LLM applications.
- **API‑first mindset** – exposing the pipeline as a REST endpoint demonstrates experience designing stateless services, request validation, and error handling.
- **Data engineering** – parsing PDFs, chunking, and managing embeddings shows you can work with unstructured data at scale.
- **Scalability awareness** – the architecture is written to be extended with horizontal scaling, caching, and observability, signaling senior‑level thinking.
- **Hiring signal** – recruiters recognize “RAG” as a high‑impact skill; building it yourself differentiates you from candidates who only read about it.

## Architecture Overview

The system is composed of four logical layers:

1. **Ingestion Layer** – A CLI script that reads source files (PDF, Markdown, plain text), splits them into chunks, and creates embeddings.
2. **Vector Store** – A persistent or in‑memory vector database (Chroma, Pinecone, or pgvector) that stores chunk embeddings and metadata.
3. **Retrieval & Generation Layer** – LangChain orchestrates the query flow: embed the user question, search the vector store for relevant chunks, and feed them to an LLM (OpenAI `gpt‑3.5‑turbo` or `gpt‑4`).
4. **API Layer** – A FastAPI app exposing a `POST /ask` endpoint that accepts a JSON payload, runs the RAG pipeline, and returns the answer with source citations.

```
+----------------+      +----------------+      +----------------+
|   CLI / Script | ---> |  Vector Store  | ---> |  LangChain RAG |
+----------------+      +----------------+      +----------------+
                                 |                     |
                                 v                     v
                           +----------------+   +----------------+
                           |   FastAPI App  |   |  LLM (OpenAI)  |
                           +----------------+   +----------------+
```

Each layer is independently testable, allowing you to swap implementations (e.g., FAISS → Pinecone) without touching the others.

## Building It Step by Step

Below is a minimal yet complete implementation. All code assumes Python 3.10+ and the packages listed in `requirements.txt`.

**1. Set up the project**

```bash
python -m venv rag-env
source rag-env/bin/activate
pip install fastapi uvicorn langchain openai chromadb pydantic pdfplumber
```

**2. Create the ingestion script (`ingest.py`)**

```python
import os
import pdfplumber
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Chroma
from langchain.document_loaders import TextLoader, PDFLoader

def load_documents(folder: str):
    docs = []
    for file in os.listdir(folder):
        path = os.path.join(folder, file)
        if file.endswith(".pdf"):
            loader = PDFLoader(path)
        elif file.endswith(".txt"):
            loader = TextLoader(path)
        else:
            continue
        docs.extend(loader.load())
    return docs

def chunk_documents(documents, chunk_size=800, chunk_overlap=100):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""]
    )
    return splitter.split_documents(documents)

def embed_and_store(chunks, persist_dir="vectorstore"):
    embeddings = OpenAIEmbeddings()
    db = Chroma.from_documents(chunks, embeddings, persist_directory=persist_dir)
    db.persist()
    return db

if __name__ == "__main__":
    docs = load_documents("data")
    chunks = chunk_documents(docs)
    embed_and_store(chunks)
    print(f"Ingested {len(chunks)} chunks into Chroma.")
```

**3. Build the RAG chain (`rag_chain.py`)**

```python
from langchain.chains import RetrievalQA
from langchain.llms import OpenAI
from langchain.vectorstores import Chroma
from langchain.embeddings import OpenAIEmbeddings

def build_chain(persist_dir="vectorstore"):
    embeddings = OpenAIEmbeddings()
    db = Chroma(persist_directory=persist_dir, embedding_function=embeddings)
    retriever = db.as_retriever(search_kwargs={"k": 4})
    llm = OpenAI(temperature=0.0)
    chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=True,
    )
    return chain
```

**4. Expose via FastAPI (`api.py`)**

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from rag_chain import build_chain

app = FastAPI(title="RAG Service")
chain = build_chain()

class Query(BaseModel):
    question: str

@app.post("/ask")
async def ask(query: Question):
    try:
        result = chain({"query": query.question})
        return {
            "answer": result["result"],
            "sources": [doc.metadata for doc in result["source_documents"]],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**5. Run the API**

```bash
uvicorn api:app --reload
```

The server will be available at `http://localhost:8000/ask`.

## Running and Testing It

1. **Prepare sample data** – create a `data/` folder with a few `.txt` or `.pdf` files.
2. **Ingest** – run `python ingest.py`. You should see a message confirming the number of chunks.
3. **Start the API** – `uvicorn api:app --reload`.
4. **Send a test request** using `curl`:

```bash
curl -X POST "http://localhost:8000/ask" \
     -H "Content-Type: application/json" \
     -d '{"question":"What is the main topic of the document?"}'
```

5. **Verify** – the response should contain an `answer` field with a natural‑language summary and a `sources` array listing the originating files.

For automated testing, add a `pytest` suite that mocks the LLM and checks that the endpoint returns a 200 status and a non‑empty answer.

## Extending It: Your Roadmap to Senior-Level

1. **Persistence & Multi‑tenant Storage** – replace Chroma with a managed vector DB like Pinecone or a self‑hosted pgvector instance. *Why:* isolates data per user and enables horizontal scaling.
2. **Caching Layer** – add Redis to cache frequent queries and embeddings. *Why:* reduces latency and OpenAI API costs under load.
3. **Observability** – instrument the pipeline with OpenTelemetry, exporting traces and metrics to Prometheus/Grafana. *Why:* makes production incidents diagnosable.
4. **Fault Tolerance & Retries** – wrap LLM calls with exponential backoff and fallback to a secondary model. *Why:* improves reliability when the primary LLM is unavailable.
5. **Benchmarking & Evaluation** – build a small evaluation harness using `ragas` to measure answer faithfulness and retrieval precision on a labeled set. *Why:* quantifies system quality and guides improvements.
6. **Async Processing** – convert ingestion and query paths to `asyncio` and use a task queue (e.g., Celery) for long‑running jobs. *Why:* enables the service to handle many concurrent users without blocking.

## Key Takeaways

- You now have a **complete, runnable RAG system** that ingests documents, stores embeddings, and answers questions via a clean API.
- The code demonstrates **data engineering, LLM integration, and API design**—competencies that hiring managers value for senior roles.
- Each component is **modular**, so you can swap in production‑grade services (Pinecone, Redis, OpenTelemetry) as you scale.
- The architecture is **ready for observability, caching, and fault tolerance**, showing foresight beyond a prototype.
- By adding benchmarks and async processing, you transform the project into a **senior‑level showcase** of distributed systems thinking.

## Further Reading

- [LangChain Documentation](https://docs.langchain.com) – official guides on chains, agents, and integrations.
- [OpenAI API Reference](https://platform.openai.com/docs) – details on embeddings and chat completions.
- [Pinecone Learn](https://www.pinecone.io/learn/) – deep dives into vector database design and best practices.
- [FAISS Documentation](https://github.com/facebookresearch/faiss) – for building high‑performance in‑memory search.
- [pgvector GitHub](https://github.com/pgvector/pgvector) – adds vector similarity search to PostgreSQL.
- [Retrieval‑Augmented Generation for Knowledge‑Intensive NLP Tasks (Lewis et al., 2020)](https://arxiv.org/abs/2005.11401) – the seminal paper that introduced RAG.