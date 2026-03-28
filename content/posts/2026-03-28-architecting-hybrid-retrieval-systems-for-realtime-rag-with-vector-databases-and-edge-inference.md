---
title: "Architecting Hybrid Retrieval Systems for Real‑Time RAG with Vector Databases and Edge Inference"
date: "2026-03-28T07:00:39.077"
draft: false
tags: ["RAG", "Vector Databases", "Edge AI", "Hybrid Retrieval", "System Architecture"]
---

## Introduction

Retrieval‑Augmented Generation (RAG) has quickly become the de‑facto pattern for building LLM‑powered applications that need up‑to‑date, factual, or domain‑specific knowledge. In a classic RAG pipeline, a user query is first **retrieved** from a knowledge store (often a vector database) and then **generated** by a large language model (LLM) conditioned on those retrieved passages.  

While the basic flow works well for offline or batch workloads, many production scenarios—customer‑support chatbots, real‑time recommendation engines, autonomous IoT devices, and AR/VR assistants—require **sub‑second latency**, **high availability**, and **privacy‑preserving inference** at the edge. Achieving these goals with a single monolithic retrieval layer is challenging:

* Purely cloud‑hosted vector stores introduce network round‑trip latency and expose potentially sensitive data.
* Edge‑only solutions struggle with the scale of embeddings and the computational cost of similarity search.
* Traditional keyword‑based retrieval (e.g., BM25) provides fast exact matches but lacks semantic coverage.

The answer is a **hybrid retrieval architecture** that combines the strengths of **dense vector search**, **sparse lexical search**, and **edge inference**. This article walks through the design principles, component choices, data flow, and practical implementation steps required to build a real‑time, production‑grade hybrid RAG system.

> **Note:** Throughout the article we assume a **dual‑deployment model**: a cloud‑native vector database (e.g., Pinecone, Weaviate, or Milvus) for large‑scale semantic search, and a lightweight edge inference engine (e.g., ONNX Runtime, TensorRT, or Apple's Core ML) that can run a compressed embedding model locally.

---

## Table of Contents
1. [Fundamentals of Hybrid Retrieval](#fundamentals-of-hybrid-retrieval)  
2. [Choosing the Right Vector Database](#choosing-the-right-vector-database)  
3. [Edge Inference: Models, Compression, and Runtime](#edge-inference-models-compression-and-runtime)  
4. [System Architecture Overview](#system-architecture-overview)  
5. [Data Flow and Latency Optimizations](#data-flow-and-latency-optimizations)  
6. [Implementation Walkthrough (Python + ONNX)](#implementation-walkthrough)  
7. [Monitoring, Scaling, and Fault Tolerance](#monitoring-scaling-and-fault-tolerance)  
8. [Security, Privacy, and Governance](#security-privacy-and-governance)  
9. [Conclusion](#conclusion)  
10. [Resources](#resources)  

---

## Fundamentals of Hybrid Retrieval <a name="fundamentals-of-hybrid-retrieval"></a>

Hybrid retrieval fuses **dense** (vector) and **sparse** (keyword) search techniques to compensate for each other's weaknesses.

| Aspect | Dense (Vector) Search | Sparse (Keyword) Search |
|--------|-----------------------|--------------------------|
| **Strength** | Captures semantic similarity, handles paraphrases, robust to lexical variation | Exact term matching, deterministic scoring, low compute |
| **Weakness** | Requires high‑dimensional similarity calculations, can miss exact phrase matches, may be noisy | Misses synonyms, struggles with out‑of‑vocabulary concepts |
| **Typical Use‑Case** | Finding relevant documents when the query phrasing differs from stored text | Filtering by precise entities, dates, or structured fields |

The hybrid approach typically follows a **two‑stage pipeline**:

1. **Coarse Retrieval** – Execute a fast lexical filter (e.g., BM25) on a subset of the corpus to prune candidates.
2. **Fine Retrieval** – Run a dense similarity search on the filtered set, optionally re‑ranking with cross‑encoders.

When combined with **edge inference**, the first stage can be executed locally on the device, dramatically cutting down the number of round‑trips to the cloud. The edge device computes a **local embedding** for the query, performs a tiny vector search against a cached subset of embeddings, and returns the top‑k IDs. Those IDs are then sent to the cloud vector store for a **global similarity refinement** before the final generation step.

---

## Choosing the Right Vector Database <a name="choosing-the-right-vector-database"></a>

A vector database is the backbone of any dense retrieval system. The following criteria are essential for real‑time hybrid RAG:

1. **Latency Guarantees** – Sub‑10 ms query latency for up to a few thousand vectors is a realistic target for high‑performance services.
2. **Scalability** – Ability to store tens of millions of embeddings while maintaining consistent latency.
3. **Hybrid Index Support** – Native support for combined dense+lexical indexes (e.g., **Weaviate's hybrid search**, **Pinecone's metadata filters**).
4. **Filtering & Metadata** – Efficient filtering on structured fields (tenant ID, document type, freshness) without a separate DB join.
5. **On‑Device Sync** – API or SDK that can export a compact snapshot for edge caching.

| Database | Hybrid Search | Real‑Time Guarantees | Open‑Source / SaaS | Edge Export |
|----------|---------------|----------------------|--------------------|-------------|
| **Pinecone** | Yes (metadata + vector) | < 5 ms for 1 M vectors (SLA) | SaaS | Export via `describe_index_stats` + batch fetch |
| **Weaviate** | Yes (BM25 + HNSW) | Configurable via `nearText` + `nearVector` | Open‑source & SaaS | `export` endpoint for snapshot |
| **Milvus** | No native lexical, but can combine with external DB | Low latency with `IVF_FLAT` or `HNSW` | Open‑source | Use `milvus_export` tool |
| **Qdrant** | Yes (filter + vector) | < 10 ms for 5 M vectors | Open‑source & SaaS | `snapshot` command |

For the remainder of the article we will use **Weaviate** because its built‑in hybrid search (`nearText` + `bm25`) simplifies the implementation and its GraphQL/REST API is edge‑friendly.

---

## Edge Inference: Models, Compression, and Runtime <a name="edge-inference-models-compression-and-runtime"></a>

Running an embedding model on the edge imposes strict constraints on **model size**, **memory footprint**, and **compute latency**. The typical workflow is:

1. **Select a Base Model** – Choose a transformer that balances quality and size (e.g., **MiniLM‑L6‑v2**, **DistilBERT‑base**, **Sentence‑Transformers**).
2. **Quantize** – Convert the model to 8‑bit integer (or even 4‑bit) using tools like **Optimum**, **ONNX Runtime Quantization**, or **TensorRT INT8**.
3. **Export to ONNX** – A platform‑agnostic format that can be executed on CPUs, GPUs, or NPUs.
4. **Choose Runtime** –  
   * **ONNX Runtime** (cross‑platform, supports quantization).  
   * **TensorRT** (NVIDIA GPUs, best performance).  
   * **Core ML** (Apple silicon).  

### Example: Quantizing MiniLM‑L6‑v2 to 8‑bit ONNX

```bash
pip install optimum[onnxruntime] transformers
python - <<'PY'
import torch
from transformers import AutoModel, AutoTokenizer
from optimum.onnxruntime import ORTModelForFeatureExtraction

model_name = "sentence-transformers/all-MiniLM-L6-v2"
tokenizer = AutoTokenizer.from_pretrained(model_name)

# Export to ONNX (fp32)
model = AutoModel.from_pretrained(model_name)
dummy_input = tokenizer("sample text", return_tensors="pt")
torch.onnx.export(
    model,
    (dummy_input["input_ids"], dummy_input["attention_mask"]),
    "minilm_fp32.onnx",
    input_names=["input_ids", "attention_mask"],
    output_names=["last_hidden_state"],
    dynamic_axes={"input_ids": {0: "batch", 1: "seq"},
                  "attention_mask": {0: "batch", 1: "seq"},
                  "last_hidden_state": {0: "batch", 1: "seq"}}
)

# Quantize to 8-bit
from optimum.onnxruntime import QuantizationConfig, quantize_static
quant_config = QuantizationConfig(
    is_static=False,
    per_channel=False,
    weight_type=QuantizationConfig.QuantizationMode.INT8,
)
quantize_static(
    model_path="minilm_fp32.onnx",
    quantized_model_path="minilm_int8.onnx",
    calibration_dataset=None,   # static quantization without calibration
    quantization_config=quant_config,
)
print("Quantized model saved to minilm_int8.onnx")
PY
```

The resulting `minilm_int8.onnx` file is typically **≈10 MB**, well within the storage limits of most edge devices and can be loaded in **≤ 5 ms** on a modern mobile CPU.

---

## System Architecture Overview <a name="system-architecture-overview"></a>

Below is a high‑level diagram of the hybrid RAG system:

```
+-------------------+          +-------------------+          +--------------------+
|   Edge Device     |          |   Cloud Edge Hub  |          |   Vector DB (Weaviate) |
| (Query + Embed)   |  <--->   | (API Gateway,    |  <--->   | (Hybrid Index,       |
|  + Local Cache    |  HTTPS   |  Auth, Rate‑lim) |  gRPC   |  Metadata Store)    |
+-------------------+          +-------------------+          +--------------------+
        |                               |                              |
        | 1. Capture user query          |                              |
        | 2. Compute local embedding     |                              |
        | 3. Local lexical filter (BM25) |                              |
        | 4. Local vector search (tiny)  |                              |
        | 5. Send candidate IDs + query  |                              |
        |    to Cloud Hub                |                              |
        |                               | 6. Global hybrid search (cloud)|
        |                               |    returns top‑k passages      |
        |                               | 7. Pass to LLM (cloud)         |
        |                               | 8. Return generated answer     |
        +-------------------------------+-------------------------------+
```

### Key Components

| Component | Responsibility | Key Technologies |
|-----------|----------------|-------------------|
| **Edge Inference Engine** | Compute query embedding, perform lightweight lexical filter | ONNX Runtime, MiniLM‑L6‑v2 |
| **Local Cache** | Store a **subset** of the most recent or most‑frequently accessed embeddings (e.g., 10 k vectors) | SQLite + Faiss (CPU) |
| **API Gateway** | Authenticate, rate‑limit, and orchestrate hybrid calls | Kong, AWS API Gateway |
| **Hybrid Search Service** | Combine lexical filter, local vector refinement, and global vector search | Weaviate GraphQL `hybrid` query |
| **LLM Generation Service** | Generate final answer using retrieved passages | OpenAI GPT‑4o, Anthropic Claude, or self‑hosted Llama 3 |
| **Observability Stack** | Metrics, tracing, logging | Prometheus, Grafana, OpenTelemetry |

---

## Data Flow and Latency Optimizations <a name="data-flow-and-latency-optimizations"></a>

### 1. Query Capture & Pre‑Processing (≤ 2 ms)

* **Tokenization** is performed using the same tokenizer as the embedding model.  
* Minimal sanitization (remove control characters, truncate to max token length) is done on the device to avoid round‑trips.

### 2. Local Embedding (≈ 5‑10 ms)

* ONNX Runtime with **CPU execution provider** on a Snapdragon 8‑gen2 yields ~10 ms for a 384‑dim embedding.  
* Quantized INT8 reduces this to ~4 ms.

### 3. Local Lexical Filter (≈ 1 ms)

* A tiny **SQLite FTS5** index (≈ 2 MB) holds the most recent 5 k documents.  
* BM25 scoring is performed locally; only the top‑N (e.g., 50) doc IDs are forwarded.

### 4. Local Vector Search (≈ 2‑3 ms)

* **Faiss IVF‑Flat** with 256 clusters on the same 5 k vectors provides sub‑millisecond distance calculations.  
* The result is a **candidate set** (IDs + scores) of size *k₁* (e.g., 20).

### 5. Cloud Hybrid Search (≈ 30‑50 ms)

* The edge device sends `{query_text, candidate_ids, top_k}` to the Cloud Hub.  
* The hub performs a **global hybrid query** in Weaviate:

```graphql
{
  Get {
    Article(
      hybrid: {
        query: "<user query>",
        alpha: 0.5,          # 0.5 weight to BM25, 0.5 to vector
        vector: [0.12, 0.34, ...], # embedding from edge (optional)
        properties: ["title", "content"],
        limit: 10
      }
      where: {
        operator: Equal,
        path: ["_id"],
        valueString: ["id1","id2",...,"id20"] # optional filter
      }
    ) {
      title
      content
      _additional { distance }
    }
  }
}
```

* The **alpha** parameter tunes the semantic vs. lexical contribution.  
* Because we restrict the search to the candidate IDs, the vector index lookup is **O(k₁ log N)** instead of **O(N)**, keeping latency low even for 100 M‑scale corpora.

### 6. Generation (≈ 150‑300 ms)

* The retrieved passages are concatenated with a prompt template and sent to the LLM via an HTTPS call.  
* For latency‑critical scenarios, **streaming** generation (e.g., OpenAI’s `stream` flag) can start delivering tokens after the first 50 ms.

### End‑to‑End Latency Summary

| Stage | Avg Latency |
|-------|-------------|
| Edge preprocessing & embedding | 5‑10 ms |
| Local lexical + vector filter | 3‑4 ms |
| Network round‑trip (edge → cloud) | 20‑30 ms (edge‑optimized 5G) |
| Cloud hybrid search | 30‑50 ms |
| LLM generation | 150‑300 ms |
| **Total** | **≈ 210‑400 ms** |

This falls comfortably within a typical **sub‑500 ms** SLA for real‑time chat assistants.

---

## Implementation Walkthrough (Python + ONNX) <a name="implementation-walkthrough"></a>

Below is a **minimal end‑to‑end prototype** that demonstrates the core steps. The code assumes:

* Edge device runs Python 3.11 with `onnxruntime`, `faiss-cpu`, `sqlite3`.
* Cloud side exposes a simple Flask endpoint that forwards the hybrid query to Weaviate.

### 1. Edge Side – Embedding and Local Search

```python
# edge_agent.py
import json
import sqlite3
import numpy as np
import onnxruntime as ort
import faiss
from transformers import AutoTokenizer

# -------------------------------------------------
# Configuration
# -------------------------------------------------
MODEL_PATH = "minilm_int8.onnx"
TOKENIZER_NAME = "sentence-transformers/all-MiniLM-L6-v2"
LOCAL_DB = "local_cache.db"
FAISS_INDEX_PATH = "local_faiss.index"
TOP_K_LOCAL = 20
TOP_N_BM25 = 50
CLOUD_ENDPOINT = "https://api.myservice.com/hybrid_search"

# -------------------------------------------------
# Load tokenizer & ONNX session (quantized)
# -------------------------------------------------
tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_NAME)
session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])

def embed_text(text: str) -> np.ndarray:
    inputs = tokenizer(text, return_tensors="np", truncation=True, max_length=128)
    ort_inputs = {k: v for k, v in inputs.items()}
    outputs = session.run(None, ort_inputs)
    # Take mean‑pool of last hidden state (axis=1)
    embedding = outputs[0].mean(axis=1)
    return embedding.astype("float32")  # shape (1, 384)

# -------------------------------------------------
# Local lexical filter using SQLite FTS5
# -------------------------------------------------
def lexical_filter(query: str, limit: int = TOP_N_BM25):
    conn = sqlite3.connect(LOCAL_DB)
    conn.enable_load_extension(True)
    conn.load_extension('fts5')
    cur = conn.cursor()
    cur.execute(
        "SELECT doc_id FROM articles_fts WHERE articles_fts MATCH ? LIMIT ?",
        (query, limit)
    )
    ids = [row[0] for row in cur.fetchall()]
    conn.close()
    return ids

# -------------------------------------------------
# Local vector search with Faiss
# -------------------------------------------------
def load_faiss_index():
    return faiss.read_index(FAISS_INDEX_PATH)

def vector_search(embedding: np.ndarray, candidate_ids: list, k: int = TOP_K_LOCAL):
    index = load_faiss_index()
    # Faiss expects (n, d) matrix; we can filter candidates by building a sub‑index
    # For simplicity, we assume the index already contains only the candidate IDs.
    distances, idx = index.search(embedding, k)
    # Map back to original IDs (stored in a separate mapping file)
    with open("id_map.json") as f:
        id_map = json.load(f)   # {faiss_idx: doc_id}
    results = [{"doc_id": id_map[str(i)], "score": float(d)} for i, d in zip(idx[0], distances[0])]
    return results

# -------------------------------------------------
# Orchestrator – combine local steps and call cloud
# -------------------------------------------------
def process_query(user_query: str):
    # 1️⃣ Embed locally
    emb = embed_text(user_query)                 # shape (1, 384)

    # 2️⃣ Lexical filter
    lexical_ids = lexical_filter(user_query)

    # 3️⃣ Vector search on cached embeddings
    vector_candidates = vector_search(emb, lexical_ids)

    # 4️⃣ Prepare payload for cloud
    payload = {
        "query": user_query,
        "embedding": emb.tolist()[0],
        "candidate_ids": [c["doc_id"] for c in vector_candidates],
        "top_k": 10
    }

    # 5️⃣ Send to cloud and get passages
    import requests
    resp = requests.post(CLOUD_ENDPOINT, json=payload, timeout=2.0)
    resp.raise_for_status()
    passages = resp.json()["passages"]

    # 6️⃣ (Optional) Local generation – omitted for brevity
    return passages

if __name__ == "__main__":
    q = "How can I reset my router to factory defaults?"
    result = process_query(q)
    print(json.dumps(result, indent=2))
```

**Explanation of the Edge Code**

* **Embedding** – Uses the quantized ONNX model for a fast forward pass.  
* **Lexical filter** – SQLite FTS5 provides BM25 scoring without any external service.  
* **Vector search** – Faiss IVF‑Flat index built from the cached 5 k embeddings; the `id_map.json` file maps Faiss internal IDs to your document IDs.  
* **Payload** – Sends both the raw embedding and the filtered IDs to the cloud, allowing the server to run a **global hybrid search** limited to those IDs.

### 2. Cloud Side – Hybrid Search Service

```python
# cloud_service.py
import json
from flask import Flask, request, jsonify
import weaviate
import os

app = Flask(__name__)

# -------------------------------------------------
# Weaviate client (environment variables for auth)
# -------------------------------------------------
client = weaviate.Client(
    url=os.getenv("WEAVIATE_URL"),
    auth_client_secret=weaviate.AuthApiKey(api_key=os.getenv("WEAVIATE_API_KEY"))
)

# -------------------------------------------------
# Helper to build hybrid query
# -------------------------------------------------
def hybrid_search(query_text, embedding, candidate_ids, top_k=10, alpha=0.5):
    # Convert embedding list to vector
    vector = embedding

    # Build GraphQL query
    graphql_query = {
        "Get": {
            "Article": {
                "hybrid": {
                    "query": query_text,
                    "vector": vector,
                    "alpha": alpha,
                    "properties": ["title", "content"],
                    "limit": top_k
                },
                "where": {
                    "operator": "Or",
                    "operands": [
                        {
                            "path": ["_id"],
                            "operator": "Equal",
                            "valueString": cid
                        } for cid in candidate_ids
                    ]
                },
                "additional": ["distance"]
            }
        }
    }

    response = client.graphql.raw_query(graphql_query)
    articles = response.get("data", {}).get("Get", {}).get("Article", [])
    # Clean up output
    passages = [
        {"title": a["title"], "content": a["content"], "score": a["_additional"]["distance"]}
        for a in articles
    ]
    return passages

# -------------------------------------------------
# Flask endpoint
# -------------------------------------------------
@app.route("/hybrid_search", methods=["POST"])
def hybrid_endpoint():
    payload = request.get_json()
    query = payload["query"]
    embedding = payload["embedding"]
    candidate_ids = payload["candidate_ids"]
    top_k = payload.get("top_k", 10)

    passages = hybrid_search(query, embedding, candidate_ids, top_k=top_k, alpha=0.6)

    return jsonify({"passages": passages})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

**Key Points**

* The **`where`** clause restricts the search to the IDs supplied by the edge device, turning a potentially expensive global vector search into a **filtered hybrid query**.  
* `alpha` controls the balance between BM25 and vector similarity; you can tune it per‑domain (e.g., higher lexical weight for legal documents).  
* The result is a list of passages that the edge device can feed to its LLM or forward to the client.

---

## Monitoring, Scaling, and Fault Tolerance <a name="monitoring-scaling-and-fault-tolerance"></a>

A production‑grade system must be observable and resilient. Below are recommended practices.

### Metrics to Export

| Metric | Description | Typical Alert |
|--------|-------------|---------------|
| `edge_latency_ms` | Time from query receipt to cloud request | > 100 ms |
| `cloud_hybrid_latency_ms` | Duration of Weaviate hybrid query | > 80 ms |
| `generation_latency_ms` | LLM response time | > 250 ms |
| `cache_hit_ratio` | Fraction of queries satisfied by local cache | < 0.6 |
| `error_rate` | 5xx responses from any component | > 1 % |

Export via **OpenTelemetry** and scrape with **Prometheus**. Visualize in **Grafana** dashboards.

### Autoscaling Strategies

* **Edge Autoscaling** – Not applicable; edge devices are static. However, you can push updated cache snapshots based on usage patterns (e.g., hot topics).  
* **Cloud Service Autoscaling** – Use Kubernetes Horizontal Pod Autoscaler (HPA) based on `cloud_hybrid_latency_ms` and request throughput.  
* **Vector DB Scaling** – For Weaviate, enable **sharding** and **replication**; the hybrid query will be distributed automatically.

### Fault Tolerance

1. **Cache Miss Fallback** – If the edge cache is empty or corrupted, the device can skip the local filter and directly send the query embedding to the cloud (increasing latency but preserving functionality).  
2. **Circuit Breaker** – Wrap the cloud HTTP call with a circuit‑breaker (e.g., `pybreaker`). If the cloud is unavailable, return a generic “I’m unable to fetch information right now” response.  
3. **Graceful Degradation** – Offer a **keyword‑only** mode when the embedding model fails to load (e.g., due to corrupted ONNX file).  

---

## Security, Privacy, and Governance <a name="security-privacy-and-governance"></a>

Hybrid RAG systems often operate on **personally identifiable information (PII)** or **proprietary corporate data**. The following controls are essential.

### Data Encryption

* **At Rest** – Encrypt the local SQLite cache with **SQLCipher**; encrypt the ONNX model file with OS‑level file encryption.  
* **In Transit** – Enforce **TLS 1.3** for all edge‑to‑cloud communications. Use **mutual TLS** for device authentication.

### Access Control

* **API Keys** – Issue per‑device API keys with scoped permissions (e.g., only `hybrid_search`). Rotate keys periodically.  
* **Zero‑Trust** – Leverage **OPA (Open Policy Agent)** in the API gateway to enforce fine‑grained policies (e.g., limit queries per minute per tenant).

### Privacy‑Preserving Embeddings

* **Differential Privacy** – Apply a small amount of Gaussian noise to the query embedding before sending it to the cloud. The noise level must be calibrated to avoid degrading retrieval quality.  
* **On‑Device Filtering** – By performing the lexical filter locally, you minimize the amount of raw text transmitted to the cloud.

### Auditing & Compliance

* Log every query ID, device ID, and response latency in an immutable store (e.g., **AWS CloudTrail** or **Azure Monitor**).  
* Implement **data retention policies**: purge cached embeddings older than 30 days, and enforce GDPR “right to be forgotten” by removing specific document IDs from both edge cache and cloud vector DB.

---

## Conclusion <a name="conclusion"></a>

Hybrid retrieval systems that blend **dense vector search**, **sparse lexical matching**, and **edge inference** provide a powerful recipe for **real‑time, low‑latency RAG** applications. By offloading the coarse lexical filter and embedding generation to the edge, you:

* **Cut network round‑trip time** dramatically.
* **Preserve privacy** by keeping raw user text on the device.
* **Scale economically** because the cloud only processes a small, pre‑filtered candidate set.

The architecture outlined in this article—leveraging a lightweight local cache, ONNX‑quantized embedding models, Faiss for fast vector look‑ups, and a cloud‑hosted Weaviate hybrid index—delivers sub‑500 ms end‑to‑end latency even at massive corpus sizes.  

When you move from prototype to production, remember to invest in **observability**, **autoscaling**, and **security**. Proper monitoring will surface latency spikes before they impact users, while robust access controls and encryption keep sensitive data safe.

By following the design patterns, code snippets, and best‑practice recommendations presented here, you’ll be equipped to build the next generation of intelligent assistants that feel **instantaneous**, **reliable**, and **respectful of user privacy**.

---

## Resources <a name="resources"></a>

1. **Weaviate Hybrid Search Documentation** – Comprehensive guide on combining BM25 and vector search.  
   [Weaviate Hybrid Search](https://weaviate.io/developers/weaviate/current/hybrid-search.html)

2. **ONNX Runtime Quantization Guide** – Official tutorial for reducing model size and latency.  
   [ONNX Runtime Quantization](https://onnxruntime.ai/docs/performance/quantization.html)

3. **FAISS – A Library for Efficient Similarity Search** – Original paper and codebase for vector indexing.  
   [FAISS GitHub](https://github.com/facebookresearch/faiss)

4. **OpenTelemetry – Observability Framework** – Instrumentation libraries for metrics, traces, and logs.  
   [OpenTelemetry](https://opentelemetry.io/)

5. **Differential Privacy for Embeddings** – Research article on adding DP noise to embeddings without breaking retrieval quality.  
   [DP Embeddings Paper (arXiv)](https://arxiv.org/abs/2106.07584)