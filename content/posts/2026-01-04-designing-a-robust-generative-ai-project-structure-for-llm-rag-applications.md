---
title: "Designing a Robust Generative AI Project Structure for LLM & RAG Applications"
date: "2026-01-04T11:05:39.464"
draft: false
tags: ["generative-ai", "project-structure", "llm", "rag", "software-architecture"]
---

Modern generative AI applications—especially those built on large language models (LLMs) and Retrieval-Augmented Generation (RAG)—can become chaotic very quickly if they’re not organized well.

Multiple model providers, complex prompt flows, vector databases, embeddings, caching, inference orchestration, and deployment considerations all compete for space in your codebase. Without a clear structure, your project becomes difficult to extend, debug, or hand off to other engineers.

This article walks through a **practical and scalable project structure** for a generative AI application:

```text
generative_ai_project/
├── config/
├── data/
├── src/
│   ├── core/
│   ├── prompts/
│   ├── rag/
│   ├── processing/
│   └── inference/
├── docs/
├── scripts/
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

We’ll cover:

- The role of each directory and file  
- How this structure supports **multiple LLM providers**  
- How it enables **RAG pipelines** and **prompt engineering**  
- Example snippets (Python, YAML, shell) to make it concrete  
- Best practices for extending and maintaining this layout  

---

## 1. Goals of This Project Structure

Before diving into the directories, it helps to be explicit about what this structure optimizes for.

This layout is designed to:

1. **Separate concerns clearly**
   - Configuration vs. code vs. data vs. documentation.
   - Core LLM abstractions vs. RAG logic vs. preprocessing vs. inference orchestration.

2. **Support multiple LLM providers and runtimes**
   - Cloud APIs (OpenAI GPT, Anthropic Claude).
   - Local / self-hosted models.
   - Future providers (e.g., Cohere, Azure OpenAI, open-source inference servers).

3. **Enable Retrieval-Augmented Generation (RAG)**
   - Clear separation of embeddings, vector stores, retrievers, and indexers.

4. **Be deployable and reproducible**
   - Docker and docker-compose support.
   - Environment setup scripts.
   - Version-controlled configuration and dependencies.

5. **Be testable and maintainable**
   - Scripted testing.
   - Modularity for unit and integration tests.
   - Easy onboarding for new contributors.

---

## 2. The Root Directory

At the top level:

```text
generative_ai_project/
├── config/
├── data/
├── src/
├── docs/
├── scripts/
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

### Key Root Files

- **`.gitignore`**  
  Prevents large or sensitive artifacts (e.g., model weights, cache files, logs) from being committed.

- **`Dockerfile`**  
  Defines how to build a containerized environment for:
  - Consistent local development.
  - Deployment to servers or cloud services.

- **`docker-compose.yml`**  
  Useful when your app relies on multiple services:
  - Vector database (e.g., Chroma, Qdrant, Weaviate, Elasticsearch).
  - API server.
  - Background workers.

- **`requirements.txt`**  
  Lists Python dependencies (could also use `pyproject.toml` or `poetry.lock` in a variant of this structure).

---

## 3. The `config/` Directory: Centralized Configuration

```text
config/
├── model_config.yaml
└── logging_config.yaml
```

Centralizing configuration makes it easier to:

- Switch models or providers without touching business logic.
- Tweak inference parameters (temperature, max tokens).
- Adjust logging verbosity per environment (dev, staging, prod).

### 3.1 `model_config.yaml`

This file defines your LLM providers, models, and global defaults.

Example:

```yaml
# config/model_config.yaml
default_provider: "openai"
default_model: "gpt-4.1-mini"

providers:
  openai:
    api_base: "https://api.openai.com/v1"
    api_key_env: "OPENAI_API_KEY"
    models:
      gpt-4.1-mini:
        max_tokens: 2048
        temperature: 0.2
        top_p: 0.9
      gpt-4.1:
        max_tokens: 4096
        temperature: 0.7
        top_p: 0.95

  anthropic:
    api_base: "https://api.anthropic.com"
    api_key_env: "ANTHROPIC_API_KEY"
    models:
      claude-3-opus:
        max_tokens: 4096
        temperature: 0.3

  local:
    endpoint: "http://localhost:8000/v1"
    models:
      llama-3-8b:
        max_tokens: 1024
        temperature: 0.1
```

Your code reads from this configuration rather than hard-coding provider details.

### 3.2 `logging_config.yaml`

Consistent logging is critical for debugging complex pipelines.

Example:

```yaml
# config/logging_config.yaml
version: 1
formatters:
  simple:
    format: "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"

handlers:
  console:
    class: logging.StreamHandler
    formatter: simple
    level: INFO
    stream: ext://sys.stdout

  file:
    class: logging.handlers.RotatingFileHandler
    formatter: simple
    level: DEBUG
    filename: "logs/app.log"
    maxBytes: 10485760  # 10MB
    backupCount: 3

root:
  level: INFO
  handlers: [console, file]

loggers:
  generative_ai_project:
    level: DEBUG
    handlers: [console, file]
    propagate: no
```

Then, in your code:

```python
import logging.config
import yaml
from pathlib import Path

def setup_logging():
    config_path = Path("config/logging_config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    logging.config.dictConfig(config)
```

---

## 4. The `data/` Directory: Runtime Data & Artifacts

```text
data/
├── cache/
├── embeddings/
└── vectordb/
```

This folder **should not** be checked into Git; it holds environment-specific, often large files.

### 4.1 `cache/`

Use this for:

- Caching LLM responses to avoid repeated calls during development and tests.
- Storing intermediate artifacts of pipelines.

You might store JSON files keyed by a hash of the prompt + parameters, or use a lightweight local DB like SQLite.

### 4.2 `embeddings/`

Stores generated embedding files, typically:

- Numpy arrays (`.npy`)  
- Parquet/Feather files  
- Checkpoints of incremental indexing

Example file layout:

```text
data/embeddings/
├── docs_v1/
│   ├── chunks.parquet
│   └── embeddings.npy
└── faq_v2/
    ├── chunks.parquet
    └── embeddings.npy
```

### 4.3 `vectordb/`

Holds on-disk indexes and vector-store artifacts, e.g.:

- FAISS index files (`.index`, `.faiss`)
- Chroma’s local directory store
- Qdrant snapshots (if using local mode)

Example:

```text
data/vectordb/
├── faiss/
│   └── docs_v1.index
└── chroma/
    └── chroma.sqlite3
```

---

## 5. The `src/` Directory: Main Application Code

```text
src/
├── core/
├── prompts/
├── rag/
├── processing/
└── inference/
```

All core logic lives here. Each subdirectory has a clear responsibility.

> **Note:** In a real project, you’d also include `__init__.py` in relevant directories to form Python packages (e.g., `src/core/__init__.py`).

---

## 6. `src/core/`: LLM Abstractions & Integrations

```text
src/core/
├── base_llm.py
├── gpt_client.py
├── claude_client.py
├── local_llm.py
└── model_factory.py
```

This layer shields the rest of the codebase from provider-specific implementations. Everyone else talks to a **common interface**, not directly to OpenAI/Anthropic/others.

### 6.1 `base_llm.py`: Common LLM Interface

Define an abstract base class:

```python
# src/core/base_llm.py
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class BaseLLM(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs: Any,
    ) -> str:
        """Generate a completion for a single prompt."""
        raise NotImplementedError

    @abstractmethod
    def generate_batch(
        self,
        prompts: List[str],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Generate completions for a batch of prompts."""
        raise NotImplementedError
```

This becomes the contract for all model clients.

### 6.2 `gpt_client.py`: OpenAI GPT Client

```python
# src/core/gpt_client.py
import os
from typing import Any, Dict, List, Optional

import openai  # or openai>=1.0.0 style client
from .base_llm import BaseLLM

class GPTClient(BaseLLM):
    def __init__(self, model_name: str, config: Dict[str, Any]):
        self.model_name = model_name
        api_key_env = config["api_key_env"]
        openai.api_key = os.environ[api_key_env]
        openai.base_url = config.get("api_base", "https://api.openai.com/v1")
        self.default_params = config["models"][model_name]

    def _merge_params(
        self,
        max_tokens: Optional[int],
        temperature: Optional[float],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        params = dict(self.default_params)
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if temperature is not None:
            params["temperature"] = temperature
        params.update(kwargs)
        return params

    def generate(self, prompt: str, **kwargs: Any) -> str:
        params = self._merge_params(**kwargs)
        response = openai.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            **params,
        )
        return response.choices[0].message.content

    def generate_batch(self, prompts: List[str], **kwargs: Any) -> List[str]:
        # Simple implementation: loop; could optimize with combined prompts
        return [self.generate(prompt, **kwargs) for prompt in prompts]
```

### 6.3 `claude_client.py`: Anthropic Claude Client

```python
# src/core/claude_client.py
import os
from typing import Any, Dict, List, Optional

from anthropic import Anthropic
from .base_llm import BaseLLM

class ClaudeClient(BaseLLM):
    def __init__(self, model_name: str, config: Dict[str, Any]):
        self.model_name = model_name
        api_key_env = config["api_key_env"]
        self.client = Anthropic(api_key=os.environ[api_key_env])
        self.default_params = config["models"][model_name]

    def _merge_params(
        self,
        max_tokens: Optional[int],
        temperature: Optional[float],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        params = dict(self.default_params)
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if temperature is not None:
            params["temperature"] = temperature
        params.update(kwargs)
        return params

    def generate(self, prompt: str, **kwargs: Any) -> str:
        params = self._merge_params(**kwargs)
        response = self.client.messages.create(
            model=self.model_name,
            max_tokens=params["max_tokens"],
            temperature=params["temperature"],
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def generate_batch(self, prompts: List[str], **kwargs: Any) -> List[str]:
        return [self.generate(prompt, **kwargs) for prompt in prompts]
```

### 6.4 `local_llm.py`: Local / Self-hosted Models

This client could talk to an HTTP server (e.g., vLLM, text-generation-inference, llama.cpp API):

```python
# src/core/local_llm.py
from typing import Any, Dict, List, Optional
import requests

from .base_llm import BaseLLM

class LocalLLM(BaseLLM):
    def __init__(self, model_name: str, config: Dict[str, Any]):
        self.model_name = model_name
        self.endpoint = config["endpoint"]
        self.default_params = config["models"][model_name]

    def _merge_params(
        self,
        max_tokens: Optional[int],
        temperature: Optional[float],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        params = dict(self.default_params)
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if temperature is not None:
            params["temperature"] = temperature
        params.update(kwargs)
        return params

    def generate(self, prompt: str, **kwargs: Any) -> str:
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            **self._merge_params(**kwargs),
        }
        response = requests.post(f"{self.endpoint}/generate", json=payload)
        response.raise_for_status()
        return response.json()["text"]

    def generate_batch(self, prompts: List[str], **kwargs: Any) -> List[str]:
        payload = {
            "model": self.model_name,
            "prompts": prompts,
            **self._merge_params(**kwargs),
        }
        response = requests.post(f"{self.endpoint}/generate_batch", json=payload)
        response.raise_for_status()
        return response.json()["texts"]
```

### 6.5 `model_factory.py`: Model Selection Logic

This file converts your `model_config.yaml` into concrete client instances.

```python
# src/core/model_factory.py
from typing import Any, Dict

import yaml
from pathlib import Path

from .base_llm import BaseLLM
from .gpt_client import GPTClient
from .claude_client import ClaudeClient
from .local_llm import LocalLLM

def load_model_config(path: str = "config/model_config.yaml") -> Dict[str, Any]:
    with open(Path(path), "r") as f:
        return yaml.safe_load(f)

def create_llm(
    provider: str | None = None,
    model_name: str | None = None,
    config: Dict[str, Any] | None = None,
) -> BaseLLM:
    if config is None:
        config = load_model_config()

    provider = provider or config["default_provider"]
    provider_cfg = config["providers"][provider]
    model_name = model_name or config["default_model"]

    if provider == "openai":
        return GPTClient(model_name, provider_cfg)
    elif provider == "anthropic":
        return ClaudeClient(model_name, provider_cfg)
    elif provider == "local":
        return LocalLLM(model_name, provider_cfg)
    else:
        raise ValueError(f"Unknown provider: {provider}")
```

Now the rest of your system can request a model via:

```python
from src.core.model_factory import create_llm

llm = create_llm()  # uses defaults in config
response = llm.generate("Explain RAG in simple terms.")
```

---

## 7. `src/prompts/`: Prompt Engineering & Chaining

```text
src/prompts/
├── templates.py
└── chain.py
```

This module focuses on **prompt structure**, not low-level model calls.

### 7.1 `templates.py`: Reusable Prompt Templates

Use simple Python template strings or a library like Jinja2.

```python
# src/prompts/templates.py
from string import Template

SYSTEM_PROMPT = """You are a helpful AI assistant. Use the provided context to answer questions concisely."""

QA_PROMPT = Template(
    """${system}

Context:
${context}

Question:
${question}

Answer in a structured and factual way. If the answer is not in the context, say you don't know."""
)

SUMMARY_PROMPT = Template(
    """${system}

Summarize the following text in bullet points:

${text}
"""
)

def build_qa_prompt(context: str, question: str) -> str:
    return QA_PROMPT.substitute(system=SYSTEM_PROMPT, context=context, question=question)

def build_summary_prompt(text: str) -> str:
    return SUMMARY_PROMPT.substitute(system=SYSTEM_PROMPT, text=text)
```

By centralizing templates, you can:

- Iterate on prompt design without touching pipeline logic.
- Localize, A/B-test, or version prompts.

### 7.2 `chain.py`: Multi-step Prompt Chaining

Implements higher-level workflows, such as:

1. Classify a query.  
2. Retrieve documents.  
3. Generate an answer.  
4. Critically review and refine the answer.

Example:

```python
# src/prompts/chain.py
from typing import Dict, Any
from src.core.base_llm import BaseLLM
from .templates import build_qa_prompt

class QAChain:
    def __init__(self, llm: BaseLLM, retriever, *, max_context_docs: int = 5):
        self.llm = llm
        self.retriever = retriever
        self.max_context_docs = max_context_docs

    def run(self, question: str) -> Dict[str, Any]:
        docs = self.retriever.retrieve(question, k=self.max_context_docs)
        context_text = "\n\n".join(doc.page_content for doc in docs)
        prompt = build_qa_prompt(context=context_text, question=question)
        answer = self.llm.generate(prompt)

        return {
            "question": question,
            "answer": answer,
            "docs": docs,
        }
```

---

## 8. `src/rag/`: Retrieval-Augmented Generation Components

```text
src/rag/
├── embedder.py
├── retriever.py
├── vector_store.py
└── indexer.py
```

These modules together implement RAG:

1. **Embedder**: converts text to vectors.  
2. **Vector store**: manages vector indices.  
3. **Indexer**: processes raw documents and inserts into the vector store.  
4. **Retriever**: queries the vector store to get relevant chunks.

### 8.1 `embedder.py`: Embedding Generation

You might use OpenAI embeddings, sentence-transformers, or a local encoder.

```python
# src/rag/embedder.py
from abc import ABC, abstractmethod
from typing import List

class BaseEmbedder(ABC):
    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        pass

    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[list[float]]:
        pass
```

Concrete implementation (e.g., OpenAI):

```python
# src/rag/openai_embedder.py
import os
from typing import List
import openai

from .embedder import BaseEmbedder

class OpenAIEmbedder(BaseEmbedder):
    def __init__(self, model: str = "text-embedding-3-large"):
        openai.api_key = os.environ["OPENAI_API_KEY"]
        self.model = model

    def embed_text(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: List[str]) -> List[list[float]]:
        response = openai.embeddings.create(
            input=texts,
            model=self.model,
        )
        return [e.embedding for e in response.data]
```

### 8.2 `vector_store.py`: Vector Store Abstraction

```python
# src/rag/vector_store.py
from abc import ABC, abstractmethod
from typing import List, Tuple

class Document:
    def __init__(self, page_content: str, metadata: dict | None = None):
        self.page_content = page_content
        self.metadata = metadata or {}

class BaseVectorStore(ABC):
    @abstractmethod
    def add(self, vectors: List[list[float]], docs: List[Document]) -> None:
        pass

    @abstractmethod
    def search(self, query_vector: list[float], k: int = 5) -> List[Tuple[Document, float]]:
        """Return list of (document, score)."""
        pass
```

Implementation example using FAISS:

```python
# src/rag/faiss_store.py
import faiss
import numpy as np
from typing import List, Tuple

from .vector_store import BaseVectorStore, Document

class FAISSVectorStore(BaseVectorStore):
    def __init__(self, dim: int):
        self.index = faiss.IndexFlatL2(dim)
        self.docs: List[Document] = []

    def add(self, vectors: List[list[float]], docs: List[Document]) -> None:
        arr = np.array(vectors, dtype="float32")
        self.index.add(arr)
        self.docs.extend(docs)

    def search(self, query_vector: list[float], k: int = 5) -> List[Tuple[Document, float]]:
        q = np.array([query_vector], dtype="float32")
        distances, indices = self.index.search(q, k)
        results: List[Tuple[Document, float]] = []
        for idx, dist in zip(indices[0], distances[0]):
            if idx == -1:
                continue
            results.append((self.docs[idx], float(dist)))
        return results
```

### 8.3 `retriever.py`: Fetching Relevant Documents

```python
# src/rag/retriever.py
from typing import List
from .embedder import BaseEmbedder
from .vector_store import BaseVectorStore, Document

class Retriever:
    def __init__(self, embedder: BaseEmbedder, vector_store: BaseVectorStore):
        self.embedder = embedder
        self.vector_store = vector_store

    def retrieve(self, query: str, k: int = 5) -> List[Document]:
        query_vec = self.embedder.embed_text(query)
        results = self.vector_store.search(query_vec, k=k)
        # results is List[(doc, score)]
        docs = [doc for doc, _ in results]
        return docs
```

### 8.4 `indexer.py`: Document Indexing Pipeline

```python
# src/rag/indexer.py
from typing import Iterable, List
from src.processing.chunking import chunk_text
from .embedder import BaseEmbedder
from .vector_store import BaseVectorStore, Document

class Indexer:
    def __init__(self, embedder: BaseEmbedder, vector_store: BaseVectorStore):
        self.embedder = embedder
        self.vector_store = vector_store

    def index_documents(self, texts: Iterable[str], metadata_list: Iterable[dict] | None = None) -> None:
        metadata_list = metadata_list or [{} for _ in texts]
        docs: List[Document] = []
        chunks: List[str] = []

        for text, meta in zip(texts, metadata_list):
            for chunk in chunk_text(text):
                chunks.append(chunk)
                docs.append(Document(page_content=chunk, metadata=meta))

        vectors = self.embedder.embed_documents(chunks)
        self.vector_store.add(vectors, docs)
```

---

## 9. `src/processing/`: Data & Text Processing

```text
src/processing/
├── chunking.py
├── tokenizer.py
└── preprocessor.py
```

This layer prepares data both for embedding and for model prompts.

### 9.1 `chunking.py`: Text Splitting

Good chunking is crucial for RAG quality.

```python
# src/processing/chunking.py
from typing import List

def chunk_text(
    text: str,
    *,
    max_chars: int = 800,
    overlap: int = 100,
) -> List[str]:
    """
    Simple character-based splitter. In production, consider token-aware splitting.
    """
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap
    return chunks
```

### 9.2 `tokenizer.py`: Tokenization Utilities

Token counters help you stay within context limits.

```python
# src/processing/tokenizer.py
from typing import List
import tiktoken  # for OpenAI, or any tokenizer lib

def get_tokenizer(model_name: str = "gpt-4.1-mini"):
    return tiktoken.encoding_for_model(model_name)

def count_tokens(text: str, model_name: str = "gpt-4.1-mini") -> int:
    enc = get_tokenizer(model_name)
    return len(enc.encode(text))

def truncate_to_tokens(text: str, max_tokens: int, model_name: str = "gpt-4.1-mini") -> str:
    enc = get_tokenizer(model_name)
    tokens = enc.encode(text)
    truncated = tokens[:max_tokens]
    return enc.decode(truncated)
```

### 9.3 `preprocessor.py`: Cleaning & Normalization

Standard place for:

- Removing boilerplate or noise.
- Lowercasing, normalizing whitespace.
- Converting HTML to text, PDFs to text, etc.

```python
# src/processing/preprocessor.py
import re

def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text
```

---

## 10. `src/inference/`: Orchestrating Inference Flows

```text
src/inference/
├── inference_engine.py
└── response_parser.py
```

While `core/` talks to raw models and `prompts/` defines text templates, the inference layer coordinates **complete workflows**—like a question-answering API endpoint.

### 10.1 `inference_engine.py`: The Orchestrator

```python
# src/inference/inference_engine.py
from typing import Dict, Any
from src.core.model_factory import create_llm
from src.rag.retriever import Retriever
from src.prompts.chain import QAChain

class InferenceEngine:
    def __init__(self, retriever: Retriever, provider: str | None = None, model_name: str | None = None):
        self.llm = create_llm(provider=provider, model_name=model_name)
        self.qa_chain = QAChain(self.llm, retriever)

    def answer_question(self, question: str) -> Dict[str, Any]:
        result = self.qa_chain.run(question)
        parsed = {
            "question": result["question"],
            "answer": result["answer"],
            "sources": [
                {
                    "snippet": doc.page_content[:200],
                    "metadata": doc.metadata,
                }
                for doc in result["docs"]
            ],
        }
        return parsed
```

This is the entry point your **API server** or **CLI tool** would call.

### 10.2 `response_parser.py`: Formatting & Structuring Outputs

If your prompts ask models to respond in JSON or markdown, parsing and validating outputs is essential.

```python
# src/inference/response_parser.py
import json
from typing import Any, Dict

def parse_json_response(text: str) -> Dict[str, Any]:
    """
    Attempts to parse model output as JSON.
    Falls back to wrapping as plain text if parsing fails.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Heuristic: try to extract fenced JSON code blocks
        if "```json" in text:
            start = text.index("```json") + len("```json")
            end = text.index("```", start)
            candidate = text[start:end].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        return {"raw_text": text}
```

---

## 11. `docs/`: Documentation

```text
docs/
├── README.md
└── SETUP.md
```

Clear documentation is especially important when the stack is multi-layered.

### 11.1 `README.md`

Usually includes:

- High-level project description.
- Architecture overview with diagrams.
- Instructions for quick start (running a sample query).
- Links to API docs, design docs, and issue trackers.

### 11.2 `SETUP.md`

Focuses on developer onboarding:

- Environment prerequisites (Python version, GPU drivers, Docker).  
- Steps to create a virtual environment.
- Running `scripts/setup_env.sh`.
- Populating `.env` files with API keys.
- Running initial index-building scripts.

---

## 12. `scripts/`: Automation & Maintenance

```text
scripts/
├── setup_env.sh
├── run_tests.sh
├── build_embeddings.py
└── cleanup.py
```

Automation scripts keep your workflows reproducible.

### 12.1 `setup_env.sh`

Example:

```bash
#!/usr/bin/env bash
set -e

python -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

echo "Environment setup complete."
```

You might extend this to:

- Create necessary directories (`data/cache`, `data/embeddings`, etc.).
- Verify presence of environment variables.

### 12.2 `run_tests.sh`

Even for prototypes, quick test commands are useful:

```bash
#!/usr/bin/env bash
set -e

source .venv/bin/activate
pytest -q
```

In a more mature setup, you’d organize tests under `tests/`, but this article focuses on the AI structure itself.

### 12.3 `build_embeddings.py`: Index Building

A CLI entry point to build or rebuild indexes.

```python
# scripts/build_embeddings.py
import argparse
from pathlib import Path

from src.rag.faiss_store import FAISSVectorStore
from src.rag.openai_embedder import OpenAIEmbedder
from src.rag.indexer import Indexer
from src.processing.preprocessor import clean_text

def load_corpus(path: Path):
    # Example: one document per file in a directory
    texts = []
    metas = []
    for file in path.glob("*.txt"):
        with open(file, "r", encoding="utf-8") as f:
            texts.append(clean_text(f.read()))
        metas.append({"source": str(file)})
    return texts, metas

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, default="corpus/")
    parser.add_argument("--dim", type=int, default=1536)
    args = parser.parse_args()

    embedder = OpenAIEmbedder()
    vector_store = FAISSVectorStore(dim=args.dim)
    indexer = Indexer(embedder, vector_store)

    texts, metas = load_corpus(Path(args.data_dir))
    indexer.index_documents(texts, metas)

    # Save FAISS index
    from pathlib import Path
    import faiss, os

    vectordb_dir = Path("data/vectordb/faiss")
    vectordb_dir.mkdir(parents=True, exist_ok=True)
    index_path = vectordb_dir / "docs.index"
    faiss.write_index(vector_store.index, str(index_path))
    print(f"Index saved to {index_path}")

if __name__ == "__main__":
    main()
```

### 12.4 `cleanup.py`: Cleaning Artifacts

Script to clear cache, temporary data, or logs:

```python
# scripts/cleanup.py
import shutil
from pathlib import Path

def remove_if_exists(path: Path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()

def main():
    for p in [
        Path("data/cache"),
        Path("logs"),
    ]:
        if p.exists():
            print(f"Removing {p}...")
            remove_if_exists(p)
    print("Cleanup complete.")

if __name__ == "__main__":
    main()
```

---

## 13. How Everything Fits Together: Example Flow

To make this concrete, here’s how a user question might flow through this architecture:

1. **API Layer (not shown)** receives a question string: `"What is Retrieval-Augmented Generation?"`.

2. It calls `InferenceEngine.answer_question(question)`:
   - `InferenceEngine` uses `model_factory` to instantiate an `LLM` (e.g., `GPTClient`), based on `model_config.yaml`.

3. `InferenceEngine` delegates to `QAChain.run(question)`:
   - `QAChain` calls `retriever.retrieve(question)`.

4. `Retriever`:
   - Uses `embedder.embed_text(question)` to get a query embedding.
   - Asks `vector_store.search(query_vector, k=5)` for the top 5 documents.
   - Returns `Document` objects representing relevant chunks.

5. `QAChain` builds a prompt via `build_qa_prompt(context, question)` (from `templates.py`).

6. The chosen `LLM` client (`GPTClient`, `ClaudeClient`, or `LocalLLM`) runs `generate(prompt)`, calling the underlying API or local server.

7. The raw text response may be parsed/formatted using `response_parser` before returning to the caller.

Throughout this process:

- Configuration comes from `config/`.  
- Intermediate data could be cached under `data/cache/`.  
- Embeddings and vector indices live under `data/embeddings/` and `data/vectordb/`.  
- Developers can inspect logs configured in `logging_config.yaml`.

---

## 14. Best Practices When Adopting This Structure

**1. Treat `src/core` as the “model boundary”**  
Keep everything model-specific inside `core/`. Other modules should not import `openai` or `anthropic` directly.

**2. Keep RAG logic model-agnostic**  
Your `retriever`, `vector_store`, and `indexer` don’t need to know whether embeddings come from OpenAI or a local model. They just accept vectors.

**3. Version your corpora and embeddings**  
Use subdirectories or naming conventions in `data/embeddings/` and `data/vectordb/` (e.g., `docs_v1`, `docs_v2`) so you can roll back or compare RAG versions.

**4. Log liberally in pipelines, sparsely in hot paths**  
RAG and inference pipelines can be opaque. Logging inputs, outputs, and key decisions (e.g., retrieved docs) is invaluable for debugging—but be mindful of PII and token costs.

**5. Leverage configuration over code changes**  
When switching from `gpt-4.1-mini` to `