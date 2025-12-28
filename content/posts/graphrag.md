---
title: "Graph RAG: Zero-to-Production Guide"
date: "2025-12-28T04:00:00+02:00"
draft: false
tags: ["graph rag", "rag", "knowledge graphs", "ai agents", "llm", "retrieval", "production ai"]
---

## Introduction

Traditional RAG systems treat knowledge as a collection of text chunks—embedded, indexed, and retrieved based on semantic similarity. This works well for simple factual lookup, but fails when questions require understanding relationships, dependencies, or multi-hop reasoning.

**Graph RAG** fundamentally reimagines how knowledge is represented: instead of flat documents, information is structured as a **graph of entities and relationships**. This enables LLMs to traverse connections, follow dependencies, and reason about how concepts relate to each other.

**The fundamental difference:**

| Classic RAG | Graph RAG |
|-------------|-----------|
| Retrieves text chunks | Retrieves entities + relationships |
| Semantic similarity | Structural traversal |
| "What looks similar?" | "How are things connected?" |
| Ambiguous connections | Explicit relationships |
| Single-hop retrieval | Multi-hop reasoning |

**Key insight:**
- **Classic RAG** retrieves text
- **Graph RAG** retrieves structure + meaning

**When Graph RAG matters:**
- Compliance and policy analysis (A affects B under condition C)
- Software architecture reasoning (dependencies, call graphs)
- Research knowledge bases (citations, influences, builds upon)
- Organizational intelligence (reporting structures, responsibilities)
- Incident analysis (cause-effect chains, cascading failures)

This guide will teach you how to design, build, and deploy production Graph RAG systems.

---

## 1. Why Graph RAG Exists

### Problems with vector-only RAG

Traditional vector-based RAG has fundamental limitations when dealing with structured knowledge:

**1. Weak multi-hop reasoning**
```
Question: "Who manages the team that owns the service that failed yesterday?"

Vector RAG: Finds documents about the service, maybe mentions teams
Problem: Can't reliably chain: Service → Team → Manager

Graph RAG: Follows edges: Service -[OWNED_BY]-> Team -[MANAGED_BY]-> Person
```

**2. Poor handling of relationships**
- Vector embeddings capture semantic similarity, not structural relationships
- "Alice reports to Bob" and "Bob reports to Alice" look similar in vector space
- Direction and type of relationship are lost

**3. Ambiguous entity resolution**
```
Documents mention:
- "John Smith in Engineering"
- "J. Smith from Product"
- "John S. who filed the bug"

Vector RAG: Treats these as separate concepts
Graph RAG: Resolves to same entity node with confidence scores
```

**4. No explicit causality or dependency modeling**
- Cannot represent "A causes B" vs. "A is correlated with B"
- No way to traverse dependency chains
- Temporal relationships are ambiguous

**5. Limited explainability**
- Why was this chunk retrieved?
- "It had high cosine similarity" isn't satisfying
- Hard to debug retrieval failures

### The fundamental mismatch

**Vector RAG answers:** "What looks similar?"

But many critical questions require: "How are these things connected?"

### What Graph RAG fixes

Graph RAG adds crucial capabilities:

**1. Explicit entity relationships**
```python
# Graph representation
(Person: "Alice") -[MANAGES]-> (Team: "Platform")
(Team: "Platform") -[OWNS]-> (Service: "Auth API")
(Service: "Auth API") -[DEPENDS_ON]-> (Service: "User DB")

# Now you can ask and answer:
# - Who is responsible for Auth API? (Alice, via ownership chain)
# - What services depend on User DB? (Traverse DEPENDS_ON edges)
# - What's Alice's scope? (All services owned by teams she manages)
```

**2. Deterministic multi-hop traversal**
- Queries follow explicit edges
- Depth and direction are controllable
- Results are reproducible and explainable

**3. Better grounding**
- Facts are stored as structured triples
- Relationships have provenance
- Contradictions are detectable

**4. Explainability**
- Show the exact traversal path
- Cite specific edges and nodes
- Prove why an answer is correct

### Examples where Graph RAG wins

**Compliance & policy analysis**
```
Question: "Is this data processing compliant with GDPR Article 6?"

Graph traversal:
DataProcessing -[USES]-> PersonalData
PersonalData -[SUBJECT_TO]-> GDPR
GDPR -[REQUIRES]-> LegalBasis
DataProcessing -[HAS_BASIS]-> Consent
```

**Software architecture reasoning**
```
Question: "What services will be affected if we take down the Auth service?"

Graph traversal:
AuthService <-[DEPENDS_ON]- [Service1, Service2, Service3]
Service1 <-[DEPENDS_ON]- [Service4]
...
```

**Research knowledge bases**
```
Question: "What are the intellectual lineage and key contributions of this paper?"

Graph traversal:
Paper -[CITES]-> PriorWork
Paper -[BUILDS_ON]-> FoundationalPaper
Paper -[AUTHORED_BY]-> Researcher
Researcher -[INFLUENCED_BY]-> Mentor
```

**Organizational intelligence**
```
Question: "Who has authority to approve this budget?"

Graph traversal:
Budget -[BELONGS_TO]-> Department
Department -[MANAGED_BY]-> Director
Director -[REPORTS_TO]-> VP
VP -[HAS_AUTHORITY]-> Approval
```

**Incident analysis**
```
Question: "What was the root cause of the outage?"

Graph traversal:
Outage -[CAUSED_BY]-> ServiceFailure
ServiceFailure -[TRIGGERED_BY]-> DeploymentEvent
DeploymentEvent -[DEPLOYED]-> BadConfig
BadConfig -[INTRODUCED_BY]-> CommitHash
```

## 2. Mental Model (Critical)

Understanding the layered architecture is essential for effective Graph RAG design.

### Three-layer architecture

```
┌──────────────────────────────────┐
│  LLM (Reasoning & Synthesis)     │  ← Plans traversal, interprets results
└─────────────┬────────────────────┘
              ↓
┌──────────────────────────────────┐
│  Graph Retrieval Engine          │  ← Executes queries, returns subgraphs
│  (Traversal & Filtering)         │
└─────────────┬────────────────────┘
              ↓
┌──────────────────────────────────┐
│  Knowledge Graph                 │  ← Stores entities, relationships, facts
│  (Entities & Relations)          │
└──────────────────────────────────┘
```

### The LLM's role

The LLM layer provides intelligence:

**Plans traversal**
- Determines which entities to start from
- Decides traversal depth and direction
- Chooses relationship types to follow

**Interprets results**
- Understands the subgraph structure
- Identifies relevant paths and patterns
- Recognizes missing or contradictory information

**Generates answers**
- Synthesizes findings from graph structure
- Provides natural language responses
- Cites specific nodes and edges

### The graph's role

The knowledge graph is the source of truth:

**Stores facts**
- Entities are nodes
- Relationships are edges
- Properties add metadata

**Encodes relationships**
- Explicit, typed connections
- Directional edges (A → B ≠ B → A)
- Multi-hop reasoning enabled

**Enables structured retrieval**
- Deterministic queries
- Reproducible results
- Explainable paths

### Key distinction

**The LLM doesn't memorize—it navigates.**

The graph stores knowledge. The LLM uses that knowledge through structured queries.

## 3. Core Components of Graph RAG

### 3.1 Knowledge Graph (KG)

A knowledge graph consists of three fundamental elements:

**1. Nodes (Entities)**
- Represent real-world entities
- Have types (Person, Service, Document, etc.)
- Contain properties (name, id, timestamps, etc.)

**2. Edges (Relationships)**
- Connect entities
- Have types (MANAGES, OWNS, DEPENDS_ON, etc.)
- Have direction (source → target)
- Can have properties (since, confidence, weight, etc.)

**3. Properties (Metadata)**
- Attributes on nodes or edges
- Enable filtering and ranking
- Provide context

**Example graph structure:**
```cypher
// Nodes
(user:Person {name: "Alice", id: "u123", role: "Engineer"})
(role:Role {name: "Admin", level: 5})
(system:System {name: "Production", env: "prod"})

// Edges
(user)-[HAS_ROLE {since: "2024-01-01"}]->(role)
(role)-[CAN_ACCESS {permission: "read_write"}]->(system)

// This encodes: Alice has Admin role and can access Production system
```

**Critical insight:** Graphs encode facts, not prose.

Instead of:
```
"Alice is an admin who can access the production system."
```

You have:
```
(Alice) -[HAS_ROLE]-> (Admin) -[CAN_ACCESS]-> (Production)
```

This enables:
- Precise queries ("Who can access Production?")
- Multi-hop traversal ("What systems can Alice access?")
- Relationship reasoning ("Does Alice have direct or indirect access?")

### 3.2 Graph Store (database layer)

**Common production graph databases:**

**1. Neo4j**
- Most popular graph database
- Cypher query language
- ACID transactions
- Strong indexing
- Good tooling ecosystem

**2. ArangoDB**
- Multi-model (graph + document + key-value)
- AQL query language
- Horizontal scaling
- Flexible schema

**3. Amazon Neptune**
- Managed service
- Supports Property Graph (Gremlin) and RDF (SPARQL)
- AWS integration
- Serverless option

**4. TigerGraph**
- High-performance analytics
- Parallel processing
- Real-time deep link analytics
- GSQL query language

**5. RDF Stores (with SPARQL)**
- Semantic web standards
- RDF triples
- Ontology support
- Examples: Virtuoso, GraphDB, Stardog

### Production requirements

When choosing a graph store, ensure it provides:

**1. ACID or strong consistency**
- Transactions for atomic updates
- Consistent reads
- Critical for maintaining graph integrity

**2. Indexing**
- Property indexes for fast lookups
- Full-text search on node properties
- Edge type indexes

**3. Query explainability**
- Query plans
- Execution statistics
- Performance profiling

**4. Access control**
- Node-level permissions
- Edge-level permissions
- Query filtering based on user roles

**5. Scalability**
- Handle growing graph size
- Reasonable query latency
- Backup and recovery

### 3.3 Graph Retriever (query execution)

The retriever is responsible for:

**Executes graph queries**
```cypher
// Example: Find all services depending on a specific service
MATCH (s:Service {name: "Auth API"})<-[:DEPENDS_ON]-(dependent:Service)
RETURN dependent.name, dependent.criticality
```

**Returns subgraphs**
- Not just lists of entities
- Complete with relationships
- Preserves structure

```python
# Example subgraph result
{
  "nodes": [
    {"id": "s1", "type": "Service", "name": "Auth API"},
    {"id": "s2", "type": "Service", "name": "User Service"},
    {"id": "s3", "type": "Service", "name": "Payment Service"}
  ],
  "edges": [
    {"from": "s2", "to": "s1", "type": "DEPENDS_ON"},
    {"from": "s3", "to": "s1", "type": "DEPENDS_ON"}
  ]
}
```

**Applies constraints**
- Depth limits (prevent traversal explosion)
- Relationship type filters
- Property filters
- Result size limits

**Key advantage:** Graph retrieval is deterministic, unlike vector similarity.

Same query → Same results (assuming graph hasn't changed)
Explainable → Can show exact traversal path
Controllable → Specify depth, direction, relationship types

## 4. Graph Construction (Most Important Step)

Graph quality determines everything. Poor graph construction makes even the best retrieval system useless.

### 4.1 Entity Extraction

**What it is:** Identifying entities from source documents and creating nodes in the knowledge graph.

**The challenge:** Entity extraction must be:
- **Accurate** - Correctly identify what is an entity
- **Normalized** - "Dr. Smith", "Smith", "Dr. James Smith" → same entity
- **Stable** - Same entity gets same ID across documents
- **Typed** - Know whether it's a Person, Service, Document, etc.

**Implementation:**

```python
from typing import List, Dict
import spacy
from dataclasses import dataclass

@dataclass
class Entity:
    """
    An entity extracted from text.
    """
    text: str  # Original text ("Dr. Smith")
    normalized_name: str  # Canonical form ("James Smith")
    entity_type: str  # "Person", "Service", "Organization", etc.
    entity_id: str  # Stable identifier ("person_jsmith")
    confidence: float  # Extraction confidence
    properties: Dict[str, any]  # Additional metadata

class EntityExtractor:
    """
    Extracts entities from documents.
    """
    def __init__(self):
        # Use NER model (spaCy, flair, or fine-tuned transformer)
        self.nlp = spacy.load("en_core_web_trf")  # Transformer-based NER
        self.entity_resolver = EntityResolver()

    async def extract_entities(
        self,
        document: str,
        doc_id: str
    ) -> List[Entity]:
        """
        Extract entities from document.
        """
        # 1. Run NER
        doc = self.nlp(document)

        entities = []
        for ent in doc.ents:
            # 2. Normalize entity name
            normalized = self._normalize_name(ent.text, ent.label_)

            # 3. Resolve to canonical entity
            entity_id = await self.entity_resolver.resolve(
                name=normalized,
                entity_type=ent.label_,
                context=document
            )

            entities.append(Entity(
                text=ent.text,
                normalized_name=normalized,
                entity_type=ent.label_,
                entity_id=entity_id,
                confidence=0.9,  # From NER model
                properties={"source_doc": doc_id, "char_span": (ent.start_char, ent.end_char)}
            ))

        return entities

    def _normalize_name(self, text: str, entity_type: str) -> str:
        """Normalize entity names."""
        # Remove titles, honorifics
        text = text.strip()
        if entity_type == "PERSON":
            # Remove Dr., Mr., Ms., etc.
            text = re.sub(r'^(Dr|Mr|Ms|Mrs|Prof)\.?\s+', '', text)
        return text

class EntityResolver:
    """
    Resolves entity mentions to canonical identities.
    """
    def __init__(self, entity_db: EntityDatabase):
        self.entity_db = entity_db

    async def resolve(
        self,
        name: str,
        entity_type: str,
        context: str
    ) -> str:
        """
        Resolve entity mention to canonical ID.
        """
        # 1. Check if exact match exists
        exact_match = await self.entity_db.find_by_name(name, entity_type)
        if exact_match:
            return exact_match.entity_id

        # 2. Fuzzy matching for similar names
        similar = await self.entity_db.find_similar(name, entity_type, threshold=0.85)
        if similar:
            # Use LLM to disambiguate
            is_same = await self._llm_disambiguate(name, similar[0].normalized_name, context)
            if is_same:
                return similar[0].entity_id

        # 3. Create new entity
        entity_id = self._generate_entity_id(name, entity_type)
        await self.entity_db.create(entity_id, name, entity_type)
        return entity_id

    def _generate_entity_id(self, name: str, entity_type: str) -> str:
        """Generate stable entity ID."""
        # Lowercase, remove spaces, add type prefix
        clean_name = name.lower().replace(" ", "_")
        prefix = entity_type.lower()[:4]
        return f"{prefix}_{clean_name}_{uuid.uuid4().hex[:6]}"

    async def _llm_disambiguate(
        self,
        name1: str,
        name2: str,
        context: str
    ) -> bool:
        """Use LLM to determine if two names refer to same entity."""
        prompt = f"""
        Context: {context}

        Are "{name1}" and "{name2}" referring to the same entity?
        Answer with only "yes" or "no".
        """
        response = await llm.generate(prompt)
        return "yes" in response.lower()
```

**Production best practices:**

1. **Use domain-specific NER** - Fine-tune models for your domain
2. **Maintain entity registry** - Centralized entity resolution database
3. **Human-in-the-loop** - Review ambiguous entity resolutions
4. **Confidence thresholds** - Only create entities with high confidence (>0.8)
5. **Deduplication** - Regularly merge duplicate entities

**This step determines graph quality.** Bad entity extraction → fragmented graph → poor retrieval.

### 4.2 Relationship Extraction

**What it is:** Extracting relationships between entities to create edges in the knowledge graph.

**Types of relationships:**

1. **Explicit relations** - Directly stated in text
   - "Service A depends on Service B"
   - "Alice reports to Bob"
   - "Paper X cites Paper Y"

2. **Implicit relations** - Inferred from co-occurrence or context
   - Entities mentioned in same sentence
   - Entities in same document section
   - Domain-specific patterns

**Implementation:**

```python
@dataclass
class Relationship:
    """
    A relationship between two entities.
    """
    source_entity_id: str
    target_entity_id: str
    relationship_type: str  # "DEPENDS_ON", "REPORTS_TO", "CITES", etc.
    confidence: float
    evidence: str  # Text snippet supporting this relationship
    properties: Dict[str, any]

class RelationshipExtractor:
    """
    Extracts relationships from text.
    """
    def __init__(self):
        self.relation_patterns = self._load_patterns()

    async def extract_relationships(
        self,
        document: str,
        entities: List[Entity]
    ) -> List[Relationship]:
        """
        Extract relationships between entities in document.
        """
        relationships = []

        # Method 1: Pattern-based extraction
        pattern_rels = self._extract_with_patterns(document, entities)
        relationships.extend(pattern_rels)

        # Method 2: LLM-based extraction
        llm_rels = await self._extract_with_llm(document, entities)
        relationships.extend(llm_rels)

        # Deduplicate and filter low-confidence
        relationships = self._deduplicate_and_filter(relationships)

        return relationships

    def _extract_with_patterns(
        self,
        document: str,
        entities: List[Entity]
    ) -> List[Relationship]:
        """
        Use regex patterns to extract explicit relationships.
        """
        relationships = []

        # Example pattern: "X depends on Y"
        depends_pattern = r'(\w+)\s+depends on\s+(\w+)'
        for match in re.finditer(depends_pattern, document, re.IGNORECASE):
            source_name = match.group(1)
            target_name = match.group(2)

            # Find matching entities
            source_entity = self._find_entity_by_name(source_name, entities)
            target_entity = self._find_entity_by_name(target_name, entities)

            if source_entity and target_entity:
                relationships.append(Relationship(
                    source_entity_id=source_entity.entity_id,
                    target_entity_id=target_entity.entity_id,
                    relationship_type="DEPENDS_ON",
                    confidence=0.95,  # High confidence from explicit pattern
                    evidence=match.group(0),
                    properties={}
                ))

        return relationships

    async def _extract_with_llm(
        self,
        document: str,
        entities: List[Entity]
    ) -> List[Relationship]:
        """
        Use LLM to extract implicit relationships.
        """
        # Prepare entity list for LLM
        entity_list = "\n".join(
            f"{i+1}. {e.normalized_name} ({e.entity_type})"
            for i, e in enumerate(entities)
        )

        prompt = f"""
        Document: {document}

        Entities:
        {entity_list}

        Extract relationships between these entities. For each relationship, specify:
        - Source entity (by number)
        - Relationship type (DEPENDS_ON, REPORTS_TO, MANAGES, OWNS, CITES, etc.)
        - Target entity (by number)
        - Evidence (text snippet)

        Return JSON array of relationships.
        """

        response = await llm.generate(prompt, format="json")

        relationships = []
        for rel_data in response:
            source_entity = entities[rel_data["source"] - 1]
            target_entity = entities[rel_data["target"] - 1]

            relationships.append(Relationship(
                source_entity_id=source_entity.entity_id,
                target_entity_id=target_entity.entity_id,
                relationship_type=rel_data["type"],
                confidence=0.75,  # Medium confidence from LLM extraction
                evidence=rel_data["evidence"],
                properties={}
            ))

        return relationships

    def _find_entity_by_name(
        self,
        name: str,
        entities: List[Entity]
    ) -> Optional[Entity]:
        """Find entity by name (fuzzy match)."""
        for entity in entities:
            if name.lower() in entity.normalized_name.lower():
                return entity
        return None

    def _deduplicate_and_filter(
        self,
        relationships: List[Relationship]
    ) -> List[Relationship]:
        """
        Remove duplicate relationships and filter by confidence.
        """
        # Deduplicate by (source, type, target) tuple
        seen = set()
        unique = []
        for rel in relationships:
            key = (rel.source_entity_id, rel.relationship_type, rel.target_entity_id)
            if key not in seen:
                seen.add(key)
                if rel.confidence >= 0.7:  # Confidence threshold
                    unique.append(rel)

        return unique
```

**Production rule:** Fewer high-confidence edges beat many weak ones.

Why? Because:
- Low-confidence edges create noise in traversal
- Ambiguous relationships confuse retrieval
- Graph becomes cluttered and hard to reason about
- Query latency increases with edge count

**Better to have:**
- 100 high-confidence relationships (>0.8)
- Than 1000 low-confidence relationships (<0.5)

### 4.3 Schema Design

**What it is:** Defining the structure of your knowledge graph—what entity types and relationship types are allowed.

**Why it matters:** Bad schemas ruin Graph RAG because:
- Ambiguous entity types make querying impossible
- Too many relationship types → can't find right path
- Inconsistent schema → fragmented graph
- No constraints → garbage data accumulates

**Schema design principles:**

```python
@dataclass
class EntityType:
    """
    Definition of an entity type in the schema.
    """
    name: str  # "Person", "Service", "Document"
    description: str
    properties: Dict[str, str]  # property_name → data_type
    required_properties: List[str]

@dataclass
class RelationshipType:
    """
    Definition of a relationship type in the schema.
    """
    name: str  # "DEPENDS_ON", "MANAGES"
    description: str
    source_entity_types: List[str]  # Allowed source types
    target_entity_types: List[str]  # Allowed target types
    direction: str  # "directed" or "undirected"
    properties: Dict[str, str]

class GraphSchema:
    """
    Schema for knowledge graph.
    """
    def __init__(self):
        self.entity_types: Dict[str, EntityType] = {}
        self.relationship_types: Dict[str, RelationshipType] = {}

    def define_entity_type(self, entity_type: EntityType):
        """Add entity type to schema."""
        self.entity_types[entity_type.name] = entity_type

    def define_relationship_type(self, rel_type: RelationshipType):
        """Add relationship type to schema."""
        self.relationship_types[rel_type.name] = rel_type

    def validate_relationship(
        self,
        rel: Relationship,
        source_type: str,
        target_type: str
    ) -> bool:
        """
        Validate that relationship conforms to schema.
        """
        rel_type = self.relationship_types.get(rel.relationship_type)
        if not rel_type:
            return False

        # Check source type is allowed
        if source_type not in rel_type.source_entity_types:
            return False

        # Check target type is allowed
        if target_type not in rel_type.target_entity_types:
            return False

        return True

# Example schema for software architecture
schema = GraphSchema()

# Define entity types
schema.define_entity_type(EntityType(
    name="Service",
    description="A microservice in the architecture",
    properties={"name": "string", "environment": "string", "version": "string"},
    required_properties=["name"]
))

schema.define_entity_type(EntityType(
    name="Person",
    description="A person (developer, manager, etc.)",
    properties={"name": "string", "email": "string", "role": "string"},
    required_properties=["name"]
))

schema.define_entity_type(EntityType(
    name="Team",
    description="A team owning services",
    properties={"name": "string", "department": "string"},
    required_properties=["name"]
))

# Define relationship types
schema.define_relationship_type(RelationshipType(
    name="DEPENDS_ON",
    description="Service A depends on Service B",
    source_entity_types=["Service"],
    target_entity_types=["Service"],
    direction="directed",
    properties={"dependency_type": "string", "critical": "boolean"}
))

schema.define_relationship_type(RelationshipType(
    name="MANAGES",
    description="Person manages Team",
    source_entity_types=["Person"],
    target_entity_types=["Team"],
    direction="directed",
    properties={"since": "date"}
))

schema.define_relationship_type(RelationshipType(
    name="OWNS",
    description="Team owns Service",
    source_entity_types=["Team"],
    target_entity_types=["Service"],
    direction="directed",
    properties={"primary_owner": "boolean"}
))
```

**Schema design guidelines:**

1. **Keep it simple** - Start with 5-10 entity types, not 50
2. **Consistent naming** - Use verbs for relationships (DEPENDS_ON, not dependency)
3. **Clear semantics** - Each relationship type has unambiguous meaning
4. **Enforce constraints** - Validate entities/relationships against schema
5. **Evolve carefully** - Schema changes require graph migration

**Bad schemas:**
- Too many types (100+ entity types)
- Ambiguous relationships ("RELATED_TO" could mean anything)
- No constraints (any entity can connect to any other)
- Inconsistent naming conventions

**Good schemas:**
- Minimal, focused set of types
- Clear, specific relationships
- Type constraints enforced
- Well-documented semantics

## 5. Graph RAG Retrieval Flow

Graph RAG retrieval is a multi-stage process where the LLM plans the traversal before executing it.

### The complete flow

```
┌──────────────────────────────────────┐
│       User Question                  │
│  "Who manages the team that owns     │
│   the Auth service?"                 │
└────────────┬─────────────────────────┘
             ↓
┌──────────────────────────────────────┐
│   1. Entity Identification           │
│   - Extract: "Auth service"          │
│   - Resolve: Service:auth_api        │
└────────────┬─────────────────────────┘
             ↓
┌──────────────────────────────────────┐
│   2. Graph Traversal Plan            │
│   - Start: Service:auth_api          │
│   - Follow: OWNED_BY → Team          │
│   - Follow: MANAGED_BY → Person      │
│   - Depth: 2 hops                    │
└────────────┬─────────────────────────┘
             ↓
┌──────────────────────────────────────┐
│   3. Subgraph Retrieval              │
│   Execute query on graph database    │
│   Return: nodes + edges              │
└────────────┬─────────────────────────┘
             ↓
┌──────────────────────────────────────┐
│   4. Optional Text Enrichment        │
│   Fetch entity descriptions from     │
│   vector store if needed             │
└────────────┬─────────────────────────┘
             ↓
┌──────────────────────────────────────┐
│   5. LLM Synthesis                   │
│   Generate natural language answer   │
│   with citations                     │
└──────────────────────────────────────┘
```

**Key insight:** The LLM does not query blindly—it plans the traversal first.

### Implementation

```python
class GraphRAGRetrieval:
    """
    Complete Graph RAG retrieval pipeline.
    """
    def __init__(
        self,
        graph_db: GraphDatabase,
        vector_store: VectorStore,
        entity_resolver: EntityResolver
    ):
        self.graph_db = graph_db
        self.vector_store = vector_store
        self.entity_resolver = entity_resolver

    async def retrieve(
        self,
        question: str
    ) -> str:
        """
        End-to-end Graph RAG retrieval.
        """
        # Stage 1: Entity Identification
        entities = await self._identify_entities(question)

        if not entities:
            return "Could not identify any entities in the question."

        # Stage 2: Query Planning
        traversal_plan = await self._plan_traversal(question, entities)

        # Stage 3: Subgraph Retrieval
        subgraph = await self._retrieve_subgraph(traversal_plan)

        # Stage 4: Optional Text Enrichment
        enriched_subgraph = await self._enrich_subgraph(subgraph)

        # Stage 5: LLM Synthesis
        answer = await self._synthesize_answer(question, enriched_subgraph)

        return answer

    async def _identify_entities(
        self,
        question: str
    ) -> List[str]:
        """
        Extract and resolve entities from question.
        """
        # Use NER to extract entity mentions
        nlp = spacy.load("en_core_web_trf")
        doc = nlp(question)

        entity_ids = []
        for ent in doc.ents:
            # Resolve to canonical entity ID
            entity_id = await self.entity_resolver.resolve(
                name=ent.text,
                entity_type=ent.label_,
                context=question
            )
            if entity_id:
                entity_ids.append(entity_id)

        return entity_ids

    async def _plan_traversal(
        self,
        question: str,
        entities: List[str]
    ) -> TraversalPlan:
        """
        Use LLM to plan graph traversal.
        """
        prompt = f"""
        Question: {question}
        Starting entities: {entities}

        Plan a graph traversal to answer this question.
        Specify:
        - Starting nodes
        - Relationship types to follow
        - Direction (outgoing/incoming)
        - Maximum depth
        - Filters (if any)

        Return as JSON.
        """

        plan_json = await llm.generate(prompt, format="json")

        return TraversalPlan(
            start_nodes=plan_json["start_nodes"],
            relationship_types=plan_json["relationship_types"],
            direction=plan_json["direction"],
            max_depth=plan_json["max_depth"],
            filters=plan_json.get("filters", {})
        )

    async def _retrieve_subgraph(
        self,
        plan: TraversalPlan
    ) -> Subgraph:
        """
        Execute traversal plan and retrieve subgraph.
        """
        # Execute Cypher query based on plan
        cypher_query = self._plan_to_cypher(plan)

        result = await self.graph_db.execute(cypher_query)

        return Subgraph(
            nodes=result["nodes"],
            edges=result["edges"]
        )

    def _plan_to_cypher(self, plan: TraversalPlan) -> str:
        """Convert traversal plan to Cypher query."""
        rel_types = "|".join(plan.relationship_types)
        direction = "->" if plan.direction == "outgoing" else "<-"

        return f"""
        MATCH path = (start)-[:{rel_types}*1..{plan.max_depth}]{direction}(end)
        WHERE start.id IN {plan.start_nodes}
        RETURN nodes(path) as nodes, relationships(path) as edges
        """

    async def _enrich_subgraph(
        self,
        subgraph: Subgraph
    ) -> Subgraph:
        """
        Optionally enrich graph structure with text descriptions.
        """
        for node in subgraph.nodes:
            if not node.get("description"):
                # Fetch description from vector store
                description = await self.vector_store.get_description(node["id"])
                node["description"] = description

        return subgraph

    async def _synthesize_answer(
        self,
        question: str,
        subgraph: Subgraph
    ) -> str:
        """
        Use LLM to generate answer from subgraph.
        """
        # Format subgraph for LLM
        graph_context = self._format_subgraph(subgraph)

        prompt = f"""
        Question: {question}

        Knowledge Graph Context:
        {graph_context}

        Using the graph structure above, answer the question.
        Cite specific nodes and relationships in your answer.
        """

        answer = await llm.generate(prompt)
        return answer

    def _format_subgraph(self, subgraph: Subgraph) -> str:
        """Format subgraph for LLM prompt."""
        formatted = "Nodes:\n"
        for node in subgraph.nodes:
            formatted += f"- {node['id']} ({node['type']}): {node.get('description', '')}\n"

        formatted += "\nRelationships:\n"
        for edge in subgraph.edges:
            formatted += f"- {edge['source']} -[{edge['type']}]-> {edge['target']}\n"

        return formatted
```

## 6. Query Planning (Agentic Layer)

Graph RAG is often agentic—the LLM reasons about how to navigate the graph before executing the traversal.

### Why planning matters

**Without planning:** Blind traversal leads to:
- Following irrelevant relationships
- Excessive depth (traversal explosion)
- Missing the right path

**With planning:** LLM determines:
- Which relationships to follow
- How deep to traverse
- What constraints to apply
- When to stop

### Planning example

```python
class GraphQueryPlanner:
    """
    Agentic query planner for Graph RAG.
    """
    async def plan_query(
        self,
        question: str,
        graph_schema: GraphSchema
    ) -> QueryPlan:
        """
        Plan graph traversal based on question and schema.
        """
        # Show LLM the available schema
        schema_description = self._describe_schema(graph_schema)

        prompt = f"""
        Available graph schema:
        {schema_description}

        Question: {question}

        Reason step-by-step:
        1. Identify relevant entities in the question
        2. Determine what relationships need to be traversed
        3. Plan the traversal path
        4. Decide constraints and depth limits

        Return your reasoning and the query plan as JSON.
        """

        response = await llm.generate(prompt, format="json")

        return QueryPlan(
            reasoning=response["reasoning"],
            start_entities=response["start_entities"],
            traversal_path=response["traversal_path"],
            max_depth=response["max_depth"],
            constraints=response.get("constraints", [])
        )

    def _describe_schema(self, schema: GraphSchema) -> str:
        """Describe graph schema for LLM."""
        description = "Entity Types:\n"
        for entity_type in schema.entity_types.values():
            description += f"- {entity_type.name}: {entity_type.description}\n"

        description += "\nRelationship Types:\n"
        for rel_type in schema.relationship_types.values():
            description += f"- {rel_type.name}: {rel_type.description}\n"
            description += f"  From: {rel_type.source_entity_types} To: {rel_type.target_entity_types}\n"

        return description
```

### Example reasoning process

```
Question: "What services will be affected if we take down the Auth service?"

LLM Reasoning:
1. Identify relevant entities:
   - "Auth service" → Entity: Service:auth_api

2. Traverse dependencies:
   - Need to find services that DEPEND_ON Auth service
   - This is an incoming traversal (other services → Auth service)

3. Collect related constraints:
   - Should include criticality information
   - May need to traverse transitively (services depending on services that depend on Auth)

4. Validate relationships:
   - Check that dependencies are marked as "critical"
   - Filter out non-production services

Query Plan:
{
  "start_nodes": ["Service:auth_api"],
  "relationship_types": ["DEPENDS_ON"],
  "direction": "incoming",
  "max_depth": 2,
  "filters": {"environment": "production"}
}
```

**The graph enforces logical structure**—the LLM can reason about relationships, not just semantic similarity.

## 7. Multi-Hop Reasoning (Where Graph RAG Shines)

Multi-hop reasoning is Graph RAG's killer feature—answering questions that require following chains of relationships.

### What is multi-hop reasoning?

**Single-hop:** Direct relationship
```
Question: "Who owns the Auth service?"
Traversal: Auth Service -[OWNED_BY]-> Platform Team
```

**Multi-hop:** Chain of relationships
```
Question: "Who manages the team that owns the Auth service?"
Traversal: Auth Service -[OWNED_BY]-> Platform Team -[MANAGED_BY]-> Alice Smith
```

### Why vector search fails at multi-hop

Vector RAG would need a document that explicitly states:
> "Alice Smith manages the team that owns the Auth service"

But with Graph RAG, we can infer this by traversing:
```
Service:auth_api -[OWNED_BY]-> Team:platform -[MANAGED_BY]-> Person:alice_smith
```

Even if no document explicitly connects Alice to the Auth service.

### Multi-hop query examples

**Example 1: Access control**

```
Question: "Can service A access customer data?"

Graph traversal:
Service:service_a
  -[HAS_ROLE]-> Role:api_client
  -[GRANTS_PERMISSION]-> Permission:read_data
  -[APPLIES_TO]-> DataType:customer_data

Answer: Yes, Service A has read access to customer data via the api_client role.
```

**Example 2: Impact analysis**

```
Question: "What's the blast radius if UserDB goes down?"

Graph traversal (depth 3):
Service:user_db
  <-[DEPENDS_ON]- Service:auth_api
  <-[DEPENDS_ON]- Service:webapp
  <-[DEPENDS_ON]- Service:mobile_api

Also:
Service:user_db
  <-[DEPENDS_ON]- Service:profile_service
  <-[DEPENDS_ON]- Service:recommendation_engine

Answer: If UserDB goes down, it would affect 5 services directly and indirectly:
auth_api, webapp, mobile_api, profile_service, and recommendation_engine.
```

**Example 3: Organizational hierarchy**

```
Question: "Who has authority to approve this budget?"

Graph traversal:
Budget:marketing_q4
  -[BELONGS_TO]-> Department:marketing
  -[MANAGED_BY]-> Person:bob_jones
  -[REPORTS_TO]-> Person:alice_ceo
  -[HAS_AUTHORITY]-> Approval:budget_approval

Answer: Alice (CEO) has authority to approve marketing Q4 budget, as she oversees Bob Jones who manages the marketing department.
```

### Implementation

```python
class MultiHopTraversal:
    """
    Multi-hop graph traversal for complex reasoning.
    """
    async def multi_hop_query(
        self,
        start_entity: str,
        path_pattern: List[str],
        max_depth: int = 3
    ) -> List[Path]:
        """
        Follow a pattern of relationships across multiple hops.
        """
        cypher_query = self._build_path_query(start_entity, path_pattern, max_depth)

        result = await self.graph_db.execute(cypher_query)

        return [Path(nodes=path["nodes"], relationships=path["rels"]) for path in result]

    def _build_path_query(
        self,
        start_entity: str,
        path_pattern: List[str],
        max_depth: int
    ) -> str:
        """
        Build Cypher query for path pattern.
        """
        # Pattern like: ["OWNED_BY", "MANAGED_BY"]
        pattern_str = "".join(f"-[:{rel}]->" for rel in path_pattern)

        return f"""
        MATCH path = (start {{id: $start_id}}){pattern_str}(end)
        WHERE length(path) <= {max_depth}
        RETURN nodes(path) as nodes, relationships(path) as rels
        """

# Usage example
traversal = MultiHopTraversal(graph_db)

# Find who manages teams that own services
paths = await traversal.multi_hop_query(
    start_entity="Service:auth_api",
    path_pattern=["OWNED_BY", "MANAGED_BY"],
    max_depth=2
)

for path in paths:
    print(f"Service: {path.nodes[0]['name']}")
    print(f"Owned by: {path.nodes[1]['name']}")
    print(f"Managed by: {path.nodes[2]['name']}")
```

**Vector search cannot do this reliably** because it lacks explicit relationship structure and traversal semantics.

8. Hybrid Graph + Vector RAG (Best Practice)
Production Graph RAG is hybrid.

Pattern:
Graph → structure

Vector → semantic detail

Flow:

sql
Copy code
Graph traversal → identify entities
Vector search → retrieve descriptions
LLM → synthesize
This combines precision + richness.

9. Answer Synthesis
The LLM receives:

Entities

Relationships

Properties

Supporting text (optional)

Best practice:

Preserve graph structure in context

Label nodes and edges explicitly

Avoid dumping raw graph queries.

10. Explainability & Trust
Graph RAG is inherently explainable.

You can show:

Traversal path

Supporting nodes

Relationship chain

This is critical for:

Compliance

Auditing

Enterprise adoption

11. Production Architecture
mathematica
Copy code
User
 ↓
Planner Agent
 ↓
Graph Query Engine
 ↓
Knowledge Graph
 ↓
Optional Vector Store
 ↓
LLM Generator
Each component is independently testable.

12. Security & Access Control
Graph-level security:

Node-level permissions

Edge-level permissions

Query filtering

Never rely on LLM safety alone.

13. Observability & Debugging
Log:

Entity matches

Traversal depth

Query latency

Returned subgraphs

Graph RAG failures are traceable — use that.

14. Performance Optimization
Limit traversal depth

Use indexes

Cache common subgraphs

Precompute views

Avoid fan-out explosions

Graph queries can become expensive quickly.

15. Common Failure Modes
❌ Over-connected graphs
❌ Weak entity resolution
❌ No schema enforcement
❌ Graph bloat
❌ Unbounded traversal

Every one of these breaks production systems.

16. When NOT to Use Graph RAG
Avoid Graph RAG when:

Data is unstructured only

Relationships don’t matter

Corpus is tiny

Latency must be ultra-low

Graph RAG trades complexity for reasoning power.

Final Takeaway
Graph RAG is:

Not a vector search replacement

Not a prompt trick

A reasoning substrate

If vector RAG answers “What sounds right?”,
Graph RAG answers “What must be true?”.