---
title: "Beyond Vector Search Mastering Long Context Retrieval with GraphRAG and Knowledge Graphs"
date: "2026-03-08T17:00:22.682"
draft: false
tags: ["vector-search", "knowledge-graphs", "retrieval-augmented-generation", "graph-rag", "nlp"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Why Traditional Vector Search Falls Short for Long Contexts](#why-traditional-vector-search-falls-short-for-long-contexts)  
3. [Enter GraphRAG: A Hybrid Retrieval Paradigm](#enter-graphrag-a-hybrid-retrieval-paradigm)  
4. [Fundamentals of Knowledge Graphs for Retrieval](#fundamentals-of-knowledge-graphs-for-retrieval)  
5. [Architectural Blueprint of a GraphRAG System](#architectural-blueprint-of-a-graphrag-system)  
6. [Building the Knowledge Graph: Practical Steps](#building-the-knowledge-graph-practical-steps)  
7. [Indexing and Embedding Strategies](#indexing-and-embedding-strategies)  
8. [Query Processing Workflow](#query-processing-workflow)  
9. [Hands‑On Example: Implementing GraphRAG with Neo4j & LangChain](#hands‑on-example-implementing-graphrag-with-neo4j--langchain)  
10. [Performance Considerations & Scaling](#performance-considerations--scaling)  
11. [Evaluation Metrics for Long‑Context Retrieval](#evaluation-metrics-for-long‑context-retrieval)  
12. [Best Practices & Common Pitfalls](#best-practices--common-pitfalls)  
13. [Future Directions](#future-directions)  
14. [Conclusion](#conclusion)  
15. [Resources](#resources)  

---

## Introduction

The explosion of large language models (LLMs) has made *retrieval‑augmented generation* (RAG) the de‑facto standard for building intelligent assistants, chatbots, and domain‑specific QA systems. Most RAG pipelines rely on **vector search**: documents are embedded into a high‑dimensional space, an approximate nearest‑neighbor (ANN) index is built, and the model retrieves the top‑k most similar chunks at inference time.

While vector search is fast and works well for short, self‑contained passages, it struggles when the user’s query requires **long‑range contextual reasoning** across many interconnected facts. In domains such as legal research, scientific literature review, or enterprise knowledge management, the relevant information often lives in a **graph of relationships** rather than a flat list of isolated snippets.

Enter **GraphRAG** – a hybrid retrieval paradigm that couples dense vector similarity with **knowledge graph** traversal. By representing entities, concepts, and their relationships explicitly, GraphRAG can surface *connected* pieces of evidence, synthesize longer narratives, and maintain factual consistency. This article dives deep into the theory, architecture, and practical implementation of GraphRAG, showing you how to move beyond classic vector search and master long‑context retrieval.

---

## Why Traditional Vector Search Falls Short for Long Contexts

### 1. Loss of Structural Information

Vector embeddings compress text into a fixed‑size vector, inevitably discarding explicit relational structure. A sentence like “*Alice authored *The Quantum Handbook* in 2020*” and “*Bob wrote *The Quantum Handbook* in 2020*” may have very similar embeddings despite referring to different authors—a subtle but critical distinction for many applications.

### 2. Context Fragmentation

Typical RAG pipelines split documents into 200‑500 token chunks. When a query needs information spread across multiple chunks (e.g., “What were the main arguments in Alice’s 2020 paper and how did they influence later work?”), the system may retrieve only a subset, leading to incomplete or contradictory answers.

### 3. Ambiguous Similarity Scores

ANN search ranks by cosine similarity, which is a *global* measure. Two passages that share a few common terms can appear highly similar even if the overall semantics diverge. This can surface “distractor” chunks that confuse the LLM.

### 4. Scaling to Massive Corpora

As the corpus grows to billions of documents, the sheer number of possible inter‑document connections explodes. Pure vector search does not scale to capture these cross‑document dependencies without an exponential increase in index size.

These shortcomings motivate a **graph‑centric** approach where entities and relationships are first identified, stored, and later traversed during retrieval.

---

## Enter GraphRAG: A Hybrid Retrieval Paradigm

**GraphRAG** (Graph‑augmented Retrieval‑Augmented Generation) combines three pillars:

1. **Entity Extraction & Linking** – Identify named entities, concepts, and key phrases, then map them to canonical identifiers (e.g., Wikidata QIDs, internal IDs).
2. **Knowledge Graph Construction** – Store entities as nodes and their semantic relations (e.g., *authored*, *cites*, *belongs_to*) as edges.
3. **Hybrid Retrieval** – At query time, a *graph query* (often a subgraph pattern) is generated, optionally enriched with vector similarity scores, to retrieve a **connected set of evidence** rather than isolated chunks.

The workflow can be visualized as:

```
[Raw Documents] → [Chunking] → [Embedding] → [Vector Index]
          ↓
[Entity Extraction] → [KG Nodes/Edges] → [Graph Store]
          ↓
[User Query] → [LLM Prompt] → [Graph Query + Vector Retrieval] → [Evidence Set] → [LLM Generation]
```

The synergy lies in letting the **graph guide the vector search**: the graph tells the system *which* chunks are likely related, while vectors rank *how* similar they are to the query.

---

## Fundamentals of Knowledge Graphs for Retrieval

### Nodes

- **Entity Nodes**: Persons, organizations, products, scientific concepts.
- **Document Nodes**: Represent entire source files or sections.
- **Literal Nodes**: Dates, numeric values, or other literals that may be important for reasoning.

### Edges

- **Semantic Relations**: `AUTHORED`, `CITES`, `PART_OF`, `HAS_ATTRIBUTE`.
- **Provenance Edges**: Link a *document node* to the *entity nodes* it contains (e.g., `MENTIONS`).
- **Embedding Edges** (optional): Store the dense vector as a property on the node for hybrid scoring.

### Graph Schemas

A well‑defined schema (often an **ontology**) ensures consistency. For a scientific literature KG, a simple schema could be:

```turtle
@prefix ex: <http://example.org/> .
ex:Paper   a rdfs:Class .
ex:Author  a rdfs:Class .
ex:Cites   a rdf:Property ; rdfs:domain ex:Paper ; rdfs:range ex:Paper .
ex:AuthoredBy a rdf:Property ; rdfs:domain ex:Paper ; rdfs:range ex:Author .
```

### Storage Options

- **Property Graphs** (Neo4j, TigerGraph) – flexible, queryable via Cypher or Gremlin.
- **RDF Triple Stores** (GraphDB, Blazegraph) – SPARQL‑centric, good for semantic web standards.
- **Hybrid Solutions** – e.g., **Weaviate** supports vector search *and* graph relations out of the box.

---

## Architectural Blueprint of a GraphRAG System

Below is a high‑level diagram of components and data flow:

```
+-------------------+      +-------------------+      +-------------------+
|   Document Store  | ---> |   Ingestion Pipe  | ---> |   Knowledge Graph |
+-------------------+      +-------------------+      +-------------------+
        |                         |                         |
        |                         v                         |
        |                 +----------------+               |
        |                 | Entity Extract |               |
        |                 +----------------+               |
        |                         |                         |
        |                         v                         |
        |                 +----------------+               |
        |                 | Chunk & Embed  |               |
        |                 +----------------+               |
        |                         |                         |
        |                         v                         |
        |                 +----------------+               |
        |                 | Vector Index   |               |
        |                 +----------------+               |
        |                         |                         |
        |                         v                         |
        |                 +----------------+               |
        |                 |  GraphRAG API  | <-------------+
        |                 +----------------+
        |                         |
        |                         v
        |                +----------------+
        |                |  LLM Generator |
        |                +----------------+
        v
+-------------------+
|   User Front‑End  |
+-------------------+
```

**Key Modules**

1. **Ingestion Pipeline** – Parses raw files (PDF, HTML, markdown), splits into chunks, extracts entities, and writes both to a vector index and the graph.
2. **Entity Extractor** – Usually a combination of a pretrained NER model (e.g., spaCy, Flair) and a linking model (e.g., BLINK, OpenAI embeddings) to map mentions to canonical IDs.
3. **Vector Index** – Typically FAISS, Annoy, or ScaNN for fast ANN retrieval.
4. **Graph Store** – Neo4j is popular for its Cypher query language and easy Python integration.
5. **GraphRAG API** – Orchestrates hybrid retrieval: runs a graph traversal, fetches candidate chunks, re‑ranks with vector similarity, and returns a context set.
6. **LLM Generator** – Takes the retrieved context and the user query, formats a prompt, and generates the final answer.

---

## Building the Knowledge Graph: Practical Steps

### Step 1: Choose a Graph Database

For this tutorial we’ll use **Neo4j** (Community Edition) because of its mature Python driver (`neo4j`) and expressive Cypher language.

```bash
# Install Neo4j locally (Docker)
docker run -d --name neo4j \
  -p7474:7474 -p7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:5
```

### Step 2: Define the Schema

```cypher
// Create constraints for fast lookup
CREATE CONSTRAINT author_id IF NOT EXISTS ON (a:Author) ASSERT a.id IS UNIQUE;
CREATE CONSTRAINT paper_id IF NOT EXISTS ON (p:Paper) ASSERT p.id IS UNIQUE;

// Example relationship types
CREATE (:Relation {type: 'AUTHORED'});
CREATE (:Relation {type: 'CITES'});
```

### Step 3: Extract Entities

```python
import spacy
from neo4j import GraphDatabase

nlp = spacy.load("en_core_web_md")   # medium-sized model with vectors

def extract_entities(text):
    doc = nlp(text)
    ents = [(ent.text, ent.label_) for ent in doc.ents]
    return ents
```

### Step 4: Populate the Graph

```python
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))

def upsert_author(tx, name):
    tx.run("""
        MERGE (a:Author {name: $name})
        ON CREATE SET a.id = randomUUID()
        RETURN a.id AS id
    """, name=name)

def upsert_paper(tx, title, abstract):
    tx.run("""
        MERGE (p:Paper {title: $title})
        ON CREATE SET p.id = randomUUID(), p.abstract = $abstract
        RETURN p.id AS id
    """, title=title, abstract=abstract)

def link_author_paper(tx, author_name, paper_title):
    tx.run("""
        MATCH (a:Author {name: $author_name})
        MATCH (p:Paper {title: $paper_title})
        MERGE (a)-[:AUTHORED]->(p)
    """, author_name=author_name, paper_title=paper_title)

# Example ingestion
with driver.session() as session:
    # Assume we have a dict `paper` with keys `title`, `abstract`
    session.write_transaction(upsert_paper, paper["title"], paper["abstract"])
    for name, _ in extract_entities(paper["abstract"]):
        if _ == "PERSON":
            session.write_transaction(upsert_author, name)
            session.write_transaction(link_author_paper, name, paper["title"])
```

### Step 5: Store Chunk Embeddings (Optional)

If you want to embed each paragraph and store the vector on the node:

```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-MiniLM-L6-v2')

def add_embedding(tx, node_label, node_id, text):
    vec = model.encode(text).tolist()
    tx.run(f"""
        MATCH (n:{node_label} {{id: $node_id}})
        SET n.embedding = $vec
    """, node_id=node_id, vec=vec)
```

Embedding stored as a property enables **vector‑augmented graph queries** later on.

---

## Indexing and Embedding Strategies

### Chunk Size Trade‑offs

- **Fine‑grained (100‑200 tokens)** – Higher recall for specific facts; more nodes in the graph.
- **Coarse‑grained (400‑800 tokens)** – Better for capturing paragraph‑level context; fewer edges.

A hybrid approach: keep both levels, linking fine chunks to their parent coarse node via `PART_OF` edges.

### Embedding Models

| Model | Size | Typical Use‑Case |
|-------|------|------------------|
| `all-MiniLM-L6-v2` | 80 MB | General‑purpose, fast inference |
| `text-embedding-3-large` (OpenAI) | API‑based | High‑quality semantic similarity |
| `E5-large` (Mistral) | 1 GB | Scientific literature, code |

Choose based on latency, cost, and domain specificity.

### ANN Index Choices

| Library | Pros | Cons |
|---------|------|------|
| **FAISS** (GPU) | Very fast, supports IVF‑PQ, HNSW | Requires C++ build, GPU memory constraints |
| **ScaNN** (Google) | Excellent recall‑latency trade‑off | Less mature Python bindings |
| **Weaviate** | Integrated vector + graph, REST API | SaaS pricing for large scale |

For a pure GraphRAG prototype, **FAISS** + Neo4j works well.

---

## Query Processing Workflow

1. **User Input** → LLM interprets intent and **generates a graph pattern** (e.g., “Find all papers authored by *Alice* that cite *Quantum Handbook*”).
2. **Graph Traversal** – The pattern is translated to a Cypher query that fetches relevant node IDs.
3. **Chunk Retrieval** – For each node, retrieve associated text chunks; optionally pull their embeddings.
4. **Hybrid Re‑ranking** – Compute cosine similarity between the query embedding and each chunk embedding; combine with graph‑based relevance scores (e.g., edge weight, hop count) using a linear blend:
   ```
   final_score = α * cosine_sim + (1-α) * graph_score
   ```
5. **Context Assembly** – Sort by `final_score`, truncate to token budget (e.g., 2,000 tokens), and format as a retrieval prompt.
6. **LLM Generation** – Pass the assembled context + user query to the LLM, optionally with a system prompt that enforces citation of sources.

### Example Cypher Query

```cypher
// Find papers authored by "Alice" that cite "Quantum Handbook"
MATCH (a:Author {name: $author})-[:AUTHORED]->(p:Paper)
WHERE EXISTS {
    MATCH (p)-[:CITES]->(:Paper {title: $cited})
}
RETURN p.id AS paper_id, p.title AS title, p.abstract AS abstract
LIMIT 10
```

The LLM can then embed the user query and re‑rank the returned abstracts.

---

## Hands‑On Example: Implementing GraphRAG with Neo4j & LangChain

Below is a minimal end‑to‑end script that:

1. Ingests a small corpus of scientific papers.
2. Builds a Neo4j knowledge graph.
3. Performs hybrid retrieval.
4. Generates an answer using OpenAI’s `gpt-4o`.

> **Prerequisites**  
> - Python 3.10+  
> - Packages: `neo4j`, `langchain`, `sentence-transformers`, `openai`, `faiss-cpu`  
> - OpenAI API key set as `OPENAI_API_KEY`.

```python
# -------------------------------------------------------------
# 1. Setup
# -------------------------------------------------------------
import os, json, faiss, numpy as np
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate

# Initialize services
driver = GraphDatabase.driver("bolt://localhost:7687",
                              auth=("neo4j", "password"))
embedder = SentenceTransformer("all-MiniLM-L6-v2")
llm = OpenAI(model="gpt-4o", temperature=0.0)

# -------------------------------------------------------------
# 2. Ingestion (simplified)
# -------------------------------------------------------------
def ingest_paper(paper):
    """
    paper: dict with keys 'title', 'abstract', 'authors' (list of strings)
    """
    with driver.session() as s:
        # Upsert paper node
        s.run("""
            MERGE (p:Paper {title: $title})
            ON CREATE SET p.id = randomUUID(),
                          p.abstract = $abstract
        """, title=paper["title"], abstract=paper["abstract"])

        # Link authors
        for author in paper["authors"]:
            s.run("""
                MERGE (a:Author {name: $name})
                ON CREATE SET a.id = randomUUID()
                WITH a
                MATCH (p:Paper {title: $title})
                MERGE (a)-[:AUTHORED]->(p)
            """, name=author, title=paper["title"])

        # Store embedding on paper node
        vec = embedder.encode(paper["abstract"]).astype("float32")
        s.run("""
            MATCH (p:Paper {title: $title})
            SET p.embedding = $vec
        """, title=paper["title"], vec=vec.tolist())

# Example corpus (two papers)
papers = [
    {
        "title": "The Quantum Handbook",
        "abstract": "An overview of quantum mechanics ...",
        "authors": ["Alice Smith"]
    },
    {
        "title": "Quantum Applications in Computing",
        "abstract": "Building on The Quantum Handbook, we explore ...",
        "authors": ["Bob Jones"]
    }
]

for p in papers:
    ingest_paper(p)

# -------------------------------------------------------------
# 3. Build FAISS index over paper embeddings
# -------------------------------------------------------------
def build_faiss_index():
    with driver.session() as s:
        result = s.run("MATCH (p:Paper) RETURN p.id AS id, p.embedding AS emb")
        ids, vectors = [], []
        for record in result:
            ids.append(record["id"])
            vectors.append(np.array(record["emb"], dtype="float32"))
        vectors = np.stack(vectors)

    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)   # Inner product (cosine after norm)
    faiss.normalize_L2(vectors)
    index.add(vectors)
    return index, ids

faiss_index, paper_ids = build_faiss_index()

# -------------------------------------------------------------
# 4. Hybrid Retrieval Function
# -------------------------------------------------------------
def retrieve(query, k=5, alpha=0.7):
    # 4.1 Embed query
    q_vec = embedder.encode(query).astype("float32")
    faiss.normalize_L2(q_vec)

    # 4.2 Vector search
    D, I = faiss_index.search(q_vec.reshape(1, -1), k*2)   # overshoot
    vec_scores = {paper_ids[i]: float(D[0][idx]) for idx, i in enumerate(I[0])}

    # 4.3 Graph pattern (simple author‑paper lookup)
    # In a real system, LLM would generate the Cypher; here we hard‑code.
    with driver.session() as s:
        result = s.run("""
            MATCH (a:Author)-[:AUTHORED]->(p:Paper)
            WHERE a.name CONTAINS $author
            RETURN p.id AS pid, p.title AS title, p.abstract AS abstract
        """, author="Alice")
        graph_scores = {}
        for rec in result:
            graph_scores[rec["pid"]] = 1.0   # binary relevance for demo

    # 4.4 Combine scores
    combined = {}
    for pid in set(vec_scores) | set(graph_scores):
        v = vec_scores.get(pid, 0.0)
        g = graph_scores.get(pid, 0.0)
        combined[pid] = alpha * v + (1 - alpha) * g

    # 4.5 Pick top‑k
    top = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:k]
    contexts = []
    with driver.session() as s:
        for pid, score in top:
            rec = s.run("MATCH (p:Paper {id: $pid}) RETURN p.title AS t, p.abstract AS a",
                        pid=pid).single()
            contexts.append(f"Title: {rec['t']}\nAbstract: {rec['a']}")
    return "\n---\n".join(contexts)

# -------------------------------------------------------------
# 5. LLM Generation
# -------------------------------------------------------------
def answer_query(user_query):
    retrieved = retrieve(user_query)
    prompt = f"""You are an expert researcher. Use ONLY the following retrieved passages to answer the question. Cite the title of each passage you use.

Passages:
{retrieved}

Question: {user_query}
Answer:"""
    response = llm(prompt)
    return response

# Demo
print(answer_query("What does Alice say about quantum mechanics?"))
```

**Explanation of the script**

- **Ingestion** creates `Author` and `Paper` nodes, links them, and stores an embedding on each paper.
- **FAISS** provides fast vector similarity over the abstracts.
- **Hybrid retrieval** blends vector similarity (`v`) with a simple graph‑derived relevance (`g`). In production you’d generate more nuanced graph scores (e.g., path length, edge weights, citation counts).
- **LLM prompt** instructs the model to ground its answer in the retrieved passages, encouraging citation.

Feel free to replace the hard‑coded author filter with an LLM‑generated Cypher query for truly dynamic GraphRAG.

---

## Performance Considerations & Scaling

| Challenge | Mitigation |
|-----------|------------|
| **Graph Traversal Latency** | Index relationship types, use Neo4j’s **Bloom** or **Graph Algorithms** plugin for pre‑computed shortest‑path caches. |
| **Embedding Storage Overhead** | Store embeddings only for high‑value nodes (e.g., papers, key entities) and use **product quantization** in FAISS to compress vectors. |
| **Token Budget** | Dynamically adjust the number of retrieved chunks based on LLM context window (e.g., 8 k tokens for GPT‑4o). |
| **Cold Start** | Pre‑populate the graph with external knowledge bases (Wikidata, DBpedia) to provide immediate coverage. |
| **Consistency of Updates** | Use **event‑driven pipelines** (Kafka → stream processing) to keep the vector index and graph in sync. |

### Horizontal Scaling

- **Vector Index** – Deploy FAISS on multiple shards behind a load balancer; each shard holds a subset of vectors.
- **Graph** – Neo4j Aura (cloud) offers clustering; alternatively, use **JanusGraph** with a distributed backend (Cassandra, HBase).
- **LLM** – Offload generation to a managed service (OpenAI, Anthropic) or run an open‑source model (Llama‑3) behind an inference server with GPU pooling.

---

## Evaluation Metrics for Long‑Context Retrieval

| Metric | Description | Typical Threshold |
|--------|-------------|-------------------|
| **Recall@k** | Fraction of relevant documents retrieved within top‑k. | ≥ 0.85 for k = 10 |
| **Precision@k** | Proportion of retrieved documents that are truly relevant. | ≥ 0.70 |
| **Mean Reciprocal Rank (MRR)** | Average of reciprocal rank of first relevant result. | ≥ 0.6 |
| **Citation Accuracy** | Percentage of model‑generated citations that match ground‑truth sources. | ≥ 0.90 |
| **Faithfulness Score** (e.g., via **FactCC**) | Measures hallucination vs. retrieved evidence. | < 0.2 error rate |

A robust evaluation pipeline combines **automatic metrics** (Recall, MRR) with **human evaluation** for factual correctness and readability.

---

## Best Practices & Common Pitfalls

### Best Practices
1. **Entity Normalization** – Map mentions to canonical IDs early; this prevents duplicate nodes.
2. **Edge Weighting** – Encode provenance confidence (e.g., `source_confidence`) to influence ranking.
3. **Hybrid Scoring Hyper‑parameter Tuning** – Use a validation set to find the optimal `α` blend between vector and graph scores.
4. **Chunk‑Level Provenance** – Store the original chunk ID on each node so you can cite the exact text.
5. **Prompt Engineering** – Explicitly ask the LLM to “cite the title of each passage you used”.

### Common Pitfalls
- **Over‑Chunking** – Too many tiny nodes explode the graph and degrade traversal speed.
- **Stale Embeddings** – Updating a document without re‑embedding leads to mismatched vector scores.
- **Graph‑Only Retrieval** – Relying solely on graph patterns can miss semantically similar but *unlinked* evidence.
- **Ignoring Token Limits** – Feeding too many retrieved passages overwhelms the LLM and degrades answer quality.
- **Neglecting Security** – Exposing raw graph queries can lead to injection attacks; always parameterize Cypher statements.

---

## Future Directions

1. **Dynamic Graph Construction** – Use LLMs themselves to propose new edges on‑the‑fly (e.g., “If the user asks about a novel relationship, create a provisional edge and re‑rank”).  
2. **Multimodal GraphRAG** – Extend nodes to store images, tables, or code snippets with corresponding embeddings (CLIP for images, CodeBERT for code).  
3. **Self‑Supervised Graph Refinement** – Leverage contrastive learning to align graph topology with embedding space, reducing the need for manual schema design.  
4. **Explainable Retrieval** – Generate a “reasoning path” visualization (graph walk) that the LLM can surface alongside its answer.  
5. **Edge‑Level Retrieval Models** – Train models that directly score *paths* (sequence of edges) rather than individual nodes, improving multi‑hop reasoning.

---

## Conclusion

Traditional vector search has propelled RAG from research to production, but its flat, similarity‑only view of data limits its ability to retrieve **long‑range, interconnected context**. GraphRAG bridges this gap by marrying the **semantic power of embeddings** with the **structural clarity of knowledge graphs**. By extracting entities, building a graph of relationships, and performing a hybrid retrieval that respects both similarity and connectivity, you can:

- Surface richer, citation‑ready evidence across multiple documents.
- Reduce hallucinations by grounding LLM generations in explicit graph paths.
- Scale to massive corpora while preserving the ability to reason over complex webs of knowledge.

The practical steps outlined—entity extraction, Neo4j graph construction, FAISS indexing, hybrid scoring, and LLM prompting—provide a concrete roadmap to implement GraphRAG today. As the ecosystem evolves with multimodal embeddings, dynamic graph updates, and more sophisticated scoring models, GraphRAG will become a cornerstone for next‑generation AI assistants that truly *understand* and *reason* over the vast, relational knowledge that powers our world.

---

## Resources

- **Neo4j Documentation** – Comprehensive guide to graph modeling, Cypher, and Python drivers.  
  [Neo4j Docs](https://neo4j.com/docs/)

- **FAISS – Facebook AI Similarity Search** – Library for efficient vector similarity search.  
  [FAISS GitHub](https://github.com/facebookresearch/faiss)

- **LangChain – Building RAG Applications** – Framework for chaining LLMs, retrieval, and prompts.  
  [LangChain Docs](https://python.langchain.com/docs/)

- **GraphRAG Paper (2024)** – Original research introducing the GraphRAG paradigm.  
  [GraphRAG: Graph‑augmented Retrieval‑Augmented Generation](https://arxiv.org/abs/2405.12345)

- **Weaviate Vector Search + Graph** – Managed solution that combines vector search with graph relationships.  
  [Weaviate](https://weaviate.io/)

- **OpenAI Retrieval‑Augmented Generation Guide** – Best practices for using OpenAI models with external knowledge.  
  [OpenAI RAG Guide](https://platform.openai.com/docs/guides/retrieval-augmented-generation)

---