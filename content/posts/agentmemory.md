---
title: "Agent Memory: Zero-to-Production Guide"
date: "2025-12-28T04:25:00+02:00"
draft: false
tags: ["agent memory", "ai agents", "llm", "rag", "long-term memory", "production ai"]
---

## Introduction

The difference between a chatbot and an agent isn't just autonomy—it's **memory**. A chatbot responds to each message in isolation. An agent remembers context, learns from outcomes, and evolves behavior over time.

**Agent memory** is the system that enables this persistence: storing relevant information, retrieving it when needed, updating beliefs as reality changes, and forgetting what's no longer relevant. Without memory, agents can't maintain long-term goals, learn from mistakes, or provide consistent experiences.

**The memory hierarchy:**

| Memory Quality | System Behavior |
|----------------|-----------------|
| **No memory** | Stateless chatbot—repeats questions, loses context |
| **Bad memory** | Dangerous agent—remembers incorrect facts, can't correct |
| **Good memory** | Reliable system—learns, adapts, maintains coherence |

**Why memory is critical:**
- **Coherence:** Agents behave consistently across interactions
- **Learning:** Systems improve from experience
- **Personalization:** Adapt to user preferences and context
- **Efficiency:** Don't re-ask known information
- **Trust:** Users can rely on the agent remembering commitments

**The challenge:**
Memory isn't just storage—it's a governed system with policies for what to remember, how long to keep it, when to update, and when to forget.

This guide covers the architecture, implementation patterns, and production considerations for building reliable agent memory systems.

---

## 1. Why Agent Memory Exists

### Without memory, agents fail

Agents without memory exhibit these critical problems:

**1. Repeat questions**
```
User: "I prefer Python over JavaScript"
Agent: "Got it, you prefer Python"

[Next session]
User: "Can you help with a coding task?"
Agent: "Sure! Which language do you prefer, Python or JavaScript?"
```

**2. Lose context**
- Cannot maintain multi-session tasks
- Forget intermediate decisions
- Drop long-running goals

**3. Forget commitments**
```
User: "Let's deploy to staging first, then production"
Agent: "Understood, I'll deploy to staging"

[Later]
Agent: "Deploying directly to production..."
```

**4. Contradict themselves**
- State fact X in one interaction
- State opposite of X later
- No way to reconcile conflicts

**5. Can't improve over time**
- Make the same mistakes repeatedly
- Don't learn from corrections
- No accumulation of expertise

### With memory, agents become capable

Memory transforms agents from reactive responders into reliable partners:

**1. Maintain long-term goals**
```python
# Agent remembers multi-session goal
{
  "goal": "Migrate database to PostgreSQL",
  "status": "in_progress",
  "completed_steps": [
    "Schema analysis",
    "Test environment setup"
  ],
  "next_step": "Data migration plan"
}
```

**2. Adapt behavior**
```
Memory: "User Alice prefers concise technical answers"
Memory: "User Bob needs detailed explanations with examples"

# Agent adjusts response style per user
```

**3. Personalize responses**
- Remember user preferences (tone, detail level, format)
- Recall past interactions and reference them
- Build contextual understanding over time

**4. Learn from outcomes**
```python
# Agent remembers what worked
{
  "action": "deploy_without_smoke_tests",
  "outcome": "failure",
  "learned": "always_run_smoke_tests_first",
  "confidence": 0.95
}
```

**5. Accumulate knowledge safely**
- Build domain expertise incrementally
- Recognize patterns across interactions
- Develop nuanced understanding of systems and policies

### The critical difference

| Without Memory | With Memory |
|----------------|-------------|
| "What's your name?" (every session) | "Hi Alice, continuing where we left off..." |
| Repeats failed approaches | Learns from mistakes |
| Inconsistent behavior | Coherent personality |
| Starts from zero each time | Builds on past interactions |
| Generic responses | Personalized assistance |

**Bottom line:** Memory is what makes an agent feel like a persistent collaborator rather than a stateless service.

## 2. Mental Model (Critical)

Agent memory is **not** one monolithic system—it's a layered architecture where each layer serves different purposes.

### The four-layer memory architecture

```
┌─────────────────────────────────────┐
│  Context Memory (Ephemeral)         │  Lifetime: Current conversation
│  - Conversation history              │  Storage: Prompt window
│  - Tool outputs in flight            │  Size: Token-limited (~100K tokens)
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│  Working Memory (Session-Level)     │  Lifetime: Current task/session
│  - Task state                        │  Storage: In-memory / Redis
│  - Plans and decisions               │  Size: KB-MB
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│  Long-Term Memory (Persistent)      │  Lifetime: Indefinite
│  - Facts and preferences             │  Storage: Vector DB / Graph DB
│  - Past outcomes                     │  Size: GB-TB
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│  Procedural Memory (Behavioral)     │  Lifetime: Until updated
│  - Skills and playbooks              │  Storage: Files / Skills
│  - Policies and rules                │  Size: KB-MB
└─────────────────────────────────────┘
```

### Why layers matter

Each layer has fundamentally different characteristics:

| Aspect | Context | Working | Long-Term | Procedural |
|--------|---------|---------|-----------|------------|
| **Lifetime** | Minutes | Hours-Days | Indefinite | Until updated |
| **Scope** | Current chat | Current task | All interactions | All agents |
| **Volatility** | Automatic | Semi-persistent | Persistent | Versioned |
| **Storage** | Prompt | RAM/Redis | DB | Files |
| **Safety** | Low risk | Medium risk | High risk | Critical |

**The key insight:** Don't treat all memory the same. Each layer needs different management strategies.

## 3. Memory Types (Canonical)

Agent memory isn't monolithic—it's a layered system where each layer serves fundamentally different purposes with different lifetimes, storage mechanisms, and risk profiles.

### 3.1 Context Memory (Ephemeral)

**What it is:**

Context memory is the agent's immediate awareness—the conversation history currently in the prompt window.

```python
class ContextMemory:
    """
    Ephemeral memory living in the prompt window.
    Automatically forgotten when conversation ends or context window fills.
    """
    def __init__(self, max_tokens: int = 100_000):
        self.messages: List[Message] = []
        self.max_tokens = max_tokens
        self.current_tokens = 0

    def add_message(self, message: Message):
        """Add message to context, evicting old messages if needed."""
        self.messages.append(message)
        self.current_tokens += message.token_count

        # Automatic eviction when context is full
        while self.current_tokens > self.max_tokens:
            evicted = self.messages.pop(0)
            self.current_tokens -= evicted.token_count

    def get_context(self) -> str:
        """Return entire conversation context for prompt."""
        return "\n".join([msg.content for msg in self.messages])
```

**Characteristics:**

1. **Short-lived** - Exists only during current conversation
2. **Token-limited** - Constrained by model context window (typically 8K-200K tokens)
3. **Automatically forgotten** - No persistence between sessions
4. **Fast access** - Directly in prompt, no retrieval needed
5. **Low cost** - No storage infrastructure required

**What belongs in context memory:**

- Current user messages
- Recent agent responses
- Tool outputs from current session
- Temporary reasoning chains

**What NEVER belongs in context memory:**

- Critical facts that must persist
- User preferences for future sessions
- Learned behaviors
- Important commitments or decisions

**Production rule:**

```python
# BAD: Relying on context memory for important information
async def deploy_service(service_name: str):
    # Assumes "staging-first" policy is still in context
    # Will break if conversation is long or multi-session
    if context_mentions("always deploy to staging first"):
        await deploy_to_staging(service_name)
    else:
        await deploy_to_production(service_name)  # DANGEROUS

# GOOD: Store policy in persistent memory
async def deploy_service(service_name: str):
    # Fetch policy from persistent memory
    policy = await memory.get_policy("deployment_workflow")
    if policy.requires_staging:
        await deploy_to_staging(service_name)
    else:
        await deploy_to_production(service_name)
```

**Never rely on context memory for anything important.**

### 3.2 Working Memory (Session-Level)

**What it is:**

Working memory is the agent's scratch pad—temporary state for the current task or session.

```python
@dataclass
class WorkingMemory:
    """
    Session-level memory for current task state.
    Persists across multiple turns but cleared when task completes.
    """
    session_id: str
    task_goal: str
    current_phase: str
    completed_steps: List[str]
    pending_actions: List[str]
    intermediate_results: Dict[str, Any]
    decisions: List[Decision]
    constraints: List[str]
    created_at: datetime
    last_updated: datetime

# Example: Multi-turn database migration task
working_memory = WorkingMemory(
    session_id="migrate-db-123",
    task_goal="Migrate from MySQL to PostgreSQL",
    current_phase="schema_analysis",
    completed_steps=[
        "Analyzed table structures",
        "Identified data type differences",
        "Created compatibility matrix"
    ],
    pending_actions=[
        "Generate migration scripts",
        "Set up test environment",
        "Run migration dry-run"
    ],
    intermediate_results={
        "incompatible_types": ["ENUM", "SET"],
        "table_count": 47,
        "estimated_downtime": "2-3 hours"
    },
    decisions=[
        Decision(
            question="Use row-by-row or bulk insert?",
            answer="bulk insert for tables >1000 rows",
            rationale="Better performance, acceptable risk"
        )
    ],
    constraints=[
        "Must complete during maintenance window",
        "Cannot modify production database directly",
        "Must preserve all foreign key relationships"
    ],
    created_at=datetime.now(),
    last_updated=datetime.now()
)
```

**Implementation patterns:**

```python
class WorkingMemoryStore:
    """
    Store for session-level working memory.
    Uses Redis or in-memory storage with TTL.
    """
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.ttl = 86400  # 24 hours

    async def save(self, session_id: str, memory: WorkingMemory):
        """Save working memory with automatic expiration."""
        key = f"working_memory:{session_id}"
        await self.redis.setex(
            key,
            self.ttl,
            json.dumps(asdict(memory))
        )

    async def load(self, session_id: str) -> Optional[WorkingMemory]:
        """Load working memory for session."""
        key = f"working_memory:{session_id}"
        data = await self.redis.get(key)
        if data:
            return WorkingMemory(**json.loads(data))
        return None

    async def update(self, session_id: str, updates: Dict[str, Any]):
        """Update specific fields in working memory."""
        memory = await self.load(session_id)
        if memory:
            for key, value in updates.items():
                setattr(memory, key, value)
            memory.last_updated = datetime.now()
            await self.save(session_id, memory)

    async def clear(self, session_id: str):
        """Clear working memory when task completes."""
        key = f"working_memory:{session_id}"
        await self.redis.delete(key)
```

**Usage example:**

```python
class TaskExecutor:
    def __init__(self, working_memory_store: WorkingMemoryStore):
        self.working_memory = working_memory_store

    async def continue_task(self, session_id: str, user_input: str):
        # Load working memory from previous turn
        memory = await self.working_memory.load(session_id)

        if not memory:
            # First turn: initialize working memory
            memory = WorkingMemory(
                session_id=session_id,
                task_goal=user_input,
                current_phase="planning",
                completed_steps=[],
                pending_actions=[],
                intermediate_results={},
                decisions=[],
                constraints=[],
                created_at=datetime.now(),
                last_updated=datetime.now()
            )

        # Agent uses working memory to maintain context
        prompt = f"""
        Current task: {memory.task_goal}
        Phase: {memory.current_phase}
        Completed: {', '.join(memory.completed_steps)}
        Next: {', '.join(memory.pending_actions)}

        User input: {user_input}

        What should we do next?
        """

        response = await llm.generate(prompt)

        # Update working memory based on action taken
        await self.working_memory.update(session_id, {
            "completed_steps": memory.completed_steps + ["new step"],
            "current_phase": "execution"
        })

        return response
```

**What belongs in working memory:**

- Current task state and progress
- Intermediate computation results
- Temporary plans and strategies
- Decisions made during current session
- Context-specific constraints

**What doesn't belong:**

- Facts that should persist across tasks
- User preferences for future use
- Learned behaviors
- Historical outcomes

**Lifetime:** Hours to days, cleared when task completes or session expires.

### 3.3 Long-Term Memory (Persistent)

**What it is:**

Long-term memory is the agent's knowledge base—facts, preferences, outcomes, and learnings that persist indefinitely across all interactions.

**This is where production agents live or die.**

```python
@dataclass
class MemoryEntry:
    """
    A single long-term memory entry.
    Immutable facts stored with metadata for governance.
    """
    id: str
    user_id: str
    content: str
    memory_type: str  # "fact", "preference", "outcome", "constraint"
    confidence: float  # 0.0 to 1.0
    source: str  # "explicit", "inferred", "learned"
    created_at: datetime
    last_accessed: datetime
    access_count: int
    embedding: List[float]  # For semantic retrieval
    tags: List[str]
    supersedes: Optional[str]  # ID of memory this replaces
    valid_until: Optional[datetime]  # For time-bound facts

# Examples of good long-term memories:
fact_memory = MemoryEntry(
    id="mem_001",
    user_id="alice",
    content="User Alice prefers Python over JavaScript for backend services",
    memory_type="preference",
    confidence=0.95,
    source="explicit",  # User explicitly stated
    created_at=datetime(2024, 1, 15),
    last_accessed=datetime(2024, 12, 28),
    access_count=23,
    embedding=[0.1, 0.2, ...],  # Vector embedding
    tags=["language_preference", "backend", "python"],
    supersedes=None,
    valid_until=None
)

outcome_memory = MemoryEntry(
    id="mem_002",
    user_id="alice",
    content="Deploying without smoke tests to production resulted in 2-hour outage on 2024-03-15",
    memory_type="outcome",
    confidence=1.0,
    source="learned",
    created_at=datetime(2024, 3, 15),
    last_accessed=datetime(2024, 12, 28),
    access_count=8,
    embedding=[0.3, 0.1, ...],
    tags=["deployment", "failure", "smoke_tests", "outage"],
    supersedes=None,
    valid_until=None
)

constraint_memory = MemoryEntry(
    id="mem_003",
    user_id="alice",
    content="Service AuthAPI cannot access UserDatabase directly; must go through UserService",
    memory_type="constraint",
    confidence=0.90,
    source="inferred",  # Learned from architecture docs and failed attempts
    created_at=datetime(2024, 6, 10),
    last_accessed=datetime(2024, 12, 27),
    access_count=15,
    embedding=[0.2, 0.4, ...],
    tags=["architecture", "access_control", "AuthAPI", "UserDatabase"],
    supersedes=None,
    valid_until=None
)
```

**Storage implementation:**

```python
class LongTermMemoryStore:
    """
    Production long-term memory with vector + structured storage.
    """
    def __init__(
        self,
        vector_db: VectorDB,  # e.g., Pinecone, Weaviate, Qdrant
        metadata_db: PostgreSQL
    ):
        self.vector_db = vector_db
        self.metadata_db = metadata_db

    async def store(self, memory: MemoryEntry):
        """Store memory with vector embedding and metadata."""
        # 1. Store vector embedding for semantic search
        await self.vector_db.upsert(
            id=memory.id,
            vector=memory.embedding,
            metadata={
                "user_id": memory.user_id,
                "memory_type": memory.memory_type,
                "tags": memory.tags,
                "confidence": memory.confidence
            }
        )

        # 2. Store full metadata in structured database
        await self.metadata_db.execute(
            """
            INSERT INTO memories (
                id, user_id, content, memory_type, confidence,
                source, created_at, last_accessed, access_count,
                tags, supersedes, valid_until
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (id) DO UPDATE SET
                last_accessed = $8,
                access_count = memories.access_count + 1
            """,
            memory.id, memory.user_id, memory.content, memory.memory_type,
            memory.confidence, memory.source, memory.created_at,
            memory.last_accessed, memory.access_count, memory.tags,
            memory.supersedes, memory.valid_until
        )

    async def retrieve(
        self,
        query: str,
        user_id: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[MemoryEntry]:
        """Retrieve relevant memories using hybrid search."""
        # 1. Vector search for semantic similarity
        query_embedding = await embed(query)
        vector_results = await self.vector_db.query(
            vector=query_embedding,
            filter={"user_id": user_id, **(filters or {})},
            top_k=limit * 2  # Get more candidates for reranking
        )

        # 2. Fetch full metadata
        memory_ids = [r.id for r in vector_results]
        memories = await self.metadata_db.fetch(
            """
            SELECT * FROM memories
            WHERE id = ANY($1)
            AND (valid_until IS NULL OR valid_until > NOW())
            ORDER BY confidence DESC, access_count DESC
            LIMIT $2
            """,
            memory_ids, limit
        )

        # 3. Update access statistics
        for memory in memories:
            memory.last_accessed = datetime.now()
            memory.access_count += 1
            await self.store(memory)  # Update metadata

        return [MemoryEntry(**m) for m in memories]

    async def update(self, memory_id: str, updates: Dict[str, Any]):
        """Update existing memory (e.g., increase confidence, add tags)."""
        memory = await self.get_by_id(memory_id)
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")

        for key, value in updates.items():
            setattr(memory, key, value)

        await self.store(memory)

    async def supersede(self, old_memory_id: str, new_memory: MemoryEntry):
        """Replace old memory with new, corrected version."""
        new_memory.supersedes = old_memory_id
        await self.store(new_memory)

        # Mark old memory as superseded (don't delete, for audit trail)
        await self.metadata_db.execute(
            "UPDATE memories SET valid_until = NOW() WHERE id = $1",
            old_memory_id
        )

    async def forget(self, memory_id: str, reason: str):
        """Explicitly forget a memory (set expiration, log reason)."""
        await self.metadata_db.execute(
            """
            UPDATE memories
            SET valid_until = NOW()
            WHERE id = $1
            """,
            memory_id
        )

        await self.metadata_db.execute(
            "INSERT INTO memory_deletions (memory_id, reason, deleted_at) VALUES ($1, $2, NOW())",
            memory_id, reason
        )
```

**Retrieval strategies:**

```python
class MemoryRetrieval:
    async def retrieve_for_context(
        self,
        query: str,
        user_id: str,
        memory_store: LongTermMemoryStore
    ) -> str:
        """
        Retrieve relevant memories and format for LLM context.
        """
        # 1. Semantic retrieval
        memories = await memory_store.retrieve(
            query=query,
            user_id=user_id,
            filters={"confidence": {"$gte": 0.7}},  # Only high-confidence
            limit=5
        )

        # 2. Format for prompt
        if not memories:
            return ""

        formatted = "## Relevant Past Knowledge:\n\n"
        for mem in memories:
            formatted += f"- **{mem.memory_type.title()}**: {mem.content}\n"
            formatted += f"  (Confidence: {mem.confidence:.0%}, Source: {mem.source})\n\n"

        return formatted

# Usage in agent:
async def generate_response(user_input: str, user_id: str):
    # Retrieve relevant long-term memories
    memory_context = await memory_retrieval.retrieve_for_context(
        query=user_input,
        user_id=user_id,
        memory_store=long_term_memory
    )

    prompt = f"""
    {memory_context}

    User: {user_input}

    Generate response taking into account the user's preferences and past context.
    """

    return await llm.generate(prompt)
```

**What belongs in long-term memory:**

- User preferences (explicit and learned)
- Important facts about users, systems, or domain
- Past outcomes and their causes
- Learned constraints and rules
- Corrected mistakes

**What doesn't belong:**

- Raw conversation logs
- Temporary task state
- Unverified assumptions
- Low-confidence inferences
- Sensitive data without explicit consent

**Production rules:**

1. **High confidence threshold** - Only store facts you're confident about (>0.7)
2. **Explicit source tracking** - Always know where memory came from
3. **Mutability** - Design for corrections and updates
4. **Governance** - Implement retention policies and user control
5. **Privacy** - Encrypt at rest, audit access, enable user deletion

### 3.4 Procedural Memory (Skills & Policies)

**What it is:**

Procedural memory defines how the agent behaves—the skills, playbooks, rules, and policies that govern action.

```python
@dataclass
class Skill:
    """
    A reusable skill that defines how to accomplish a specific task.
    """
    name: str
    description: str
    when_to_use: str
    steps: List[str]
    required_tools: List[str]
    safety_checks: List[str]
    examples: List[Dict[str, str]]

# Example: Code review skill
code_review_skill = Skill(
    name="code_review",
    description="Systematic code review process for pull requests",
    when_to_use="When user requests code review or PR analysis",
    steps=[
        "1. Read the code changes in the PR",
        "2. Check for security vulnerabilities (SQL injection, XSS, etc.)",
        "3. Verify error handling and edge cases",
        "4. Check for performance issues",
        "5. Verify tests exist and cover new code",
        "6. Check code style and maintainability",
        "7. Provide constructive feedback with specific suggestions"
    ],
    required_tools=["read_file", "grep", "run_tests"],
    safety_checks=[
        "Never approve changes that introduce security vulnerabilities",
        "Never skip test verification",
        "Always check for breaking changes in public APIs"
    ],
    examples=[
        {
            "input": "Review PR #123",
            "approach": "Read files → Check security → Verify tests → Provide feedback"
        }
    ]
)

@dataclass
class Policy:
    """
    A rule or constraint that governs agent behavior.
    """
    name: str
    description: str
    rule: str
    enforcement: str  # "hard" (must follow) or "soft" (should follow)
    rationale: str
    exceptions: List[str]

# Example: Deployment policy
deployment_policy = Policy(
    name="staging_first_deployment",
    description="Always deploy to staging before production",
    rule="For any deployment, first deploy to staging environment, verify functionality, then deploy to production",
    enforcement="hard",
    rationale="Prevents production outages from untested changes. Required after 2024-03-15 outage incident.",
    exceptions=[
        "Emergency security patches with explicit approval",
        "Rollback to previous known-good version"
    ]
)

# Example: Tool usage policy
tool_safety_policy = Policy(
    name="destructive_command_approval",
    description="Require human approval for destructive operations",
    rule="Before executing rm, DROP TABLE, DELETE FROM, or similar destructive commands, get explicit human confirmation",
    enforcement="hard",
    rationale="Prevents accidental data loss",
    exceptions=["Operations in explicitly labeled test environments"]
)
```

**Implementation patterns:**

```python
class ProceduralMemoryStore:
    """
    Storage for skills and policies.
    Usually file-based or database-backed.
    """
    def __init__(self, skills_dir: Path, policies_dir: Path):
        self.skills_dir = skills_dir
        self.policies_dir = policies_dir
        self.skills: Dict[str, Skill] = {}
        self.policies: Dict[str, Policy] = {}
        self.load_all()

    def load_all(self):
        """Load all skills and policies from disk."""
        # Load skills
        for skill_file in self.skills_dir.glob("*.yaml"):
            with open(skill_file) as f:
                skill_data = yaml.safe_load(f)
                skill = Skill(**skill_data)
                self.skills[skill.name] = skill

        # Load policies
        for policy_file in self.policies_dir.glob("*.yaml"):
            with open(policy_file) as f:
                policy_data = yaml.safe_load(f)
                policy = Policy(**policy_data)
                self.policies[policy.name] = policy

    def get_skill(self, name: str) -> Optional[Skill]:
        """Retrieve skill by name."""
        return self.skills.get(name)

    def get_applicable_policies(
        self,
        action: str,
        context: Dict[str, Any]
    ) -> List[Policy]:
        """Get policies that apply to a specific action."""
        applicable = []
        for policy in self.policies.values():
            if self._policy_applies(policy, action, context):
                applicable.append(policy)
        return applicable

    def _policy_applies(
        self,
        policy: Policy,
        action: str,
        context: Dict[str, Any]
    ) -> bool:
        """Determine if policy applies to action."""
        # Simple keyword matching (production would use LLM or rules engine)
        action_lower = action.lower()
        for keyword in policy.rule.lower().split():
            if keyword in action_lower:
                return True
        return False

class SkillExecutor:
    """
    Executes skills according to their defined procedures.
    """
    def __init__(
        self,
        procedural_memory: ProceduralMemoryStore,
        tools: ToolRegistry
    ):
        self.procedural_memory = procedural_memory
        self.tools = tools

    async def execute_skill(
        self,
        skill_name: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a skill following its defined steps."""
        skill = self.procedural_memory.get_skill(skill_name)
        if not skill:
            raise ValueError(f"Skill '{skill_name}' not found")

        # Verify required tools are available
        for tool_name in skill.required_tools:
            if not self.tools.has(tool_name):
                raise ValueError(f"Required tool '{tool_name}' not available")

        # Execute steps
        results = []
        for i, step in enumerate(skill.steps):
            print(f"Step {i+1}/{len(skill.steps)}: {step}")

            # LLM interprets step and executes appropriate tools
            step_result = await self._execute_step(step, context, skill)
            results.append(step_result)

            # Check if step failed
            if step_result.get("status") == "failed":
                return {
                    "status": "failed",
                    "failed_at_step": i + 1,
                    "error": step_result.get("error"),
                    "completed_steps": results
                }

        return {
            "status": "success",
            "results": results
        }

    async def _execute_step(
        self,
        step: str,
        context: Dict[str, Any],
        skill: Skill
    ) -> Dict[str, Any]:
        """Execute a single step of a skill."""
        # Generate prompt for LLM to execute this step
        prompt = f"""
        Skill: {skill.name}
        Current step: {step}
        Context: {json.dumps(context)}

        Execute this step using available tools.
        Remember to follow safety checks: {', '.join(skill.safety_checks)}
        """

        # LLM plans and executes tools for this step
        return await llm_with_tools.execute(prompt)

class PolicyEnforcement:
    """
    Enforces policies before actions are executed.
    """
    def __init__(self, procedural_memory: ProceduralMemoryStore):
        self.procedural_memory = procedural_memory

    async def check_action(
        self,
        action: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        Check if action is allowed under current policies.
        Returns (allowed, violations).
        """
        applicable_policies = self.procedural_memory.get_applicable_policies(
            action, context
        )

        violations = []
        for policy in applicable_policies:
            # Check if action violates policy
            if self._violates_policy(policy, action, context):
                if policy.enforcement == "hard":
                    violations.append(
                        f"BLOCKED: {policy.name} - {policy.rule}"
                    )
                else:
                    violations.append(
                        f"WARNING: {policy.name} - {policy.rule}"
                    )

        # Hard policy violations block action
        hard_violations = [v for v in violations if v.startswith("BLOCKED")]
        allowed = len(hard_violations) == 0

        return allowed, violations

    def _violates_policy(
        self,
        policy: Policy,
        action: str,
        context: Dict[str, Any]
    ) -> bool:
        """Check if action violates policy."""
        # Production would use LLM or rules engine
        # Simple implementation: check if action contains forbidden patterns
        forbidden_patterns = ["rm -rf", "DROP TABLE", "DELETE FROM"]
        action_lower = action.lower()

        for pattern in forbidden_patterns:
            if pattern.lower() in action_lower:
                # Check if exception applies
                for exception in policy.exceptions:
                    if exception.lower() in str(context).lower():
                        return False  # Exception applies
                return True  # Violation

        return False
```

**Usage in agent:**

```python
class PolicyAwareAgent:
    def __init__(
        self,
        procedural_memory: ProceduralMemoryStore,
        policy_enforcement: PolicyEnforcement
    ):
        self.procedural_memory = procedural_memory
        self.policy_enforcement = policy_enforcement

    async def execute_action(
        self,
        action: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute action after policy check."""
        # 1. Check policies
        allowed, violations = await self.policy_enforcement.check_action(
            action, context
        )

        if not allowed:
            return {
                "status": "blocked",
                "reason": "Policy violation",
                "violations": violations
            }

        # 2. Warn about soft violations
        if violations:
            print(f"⚠️  Policy warnings: {violations}")

        # 3. Execute action
        result = await self._execute(action, context)

        return result
```

**What belongs in procedural memory:**

- Skills and playbooks (how to do specific tasks)
- Policies and rules (what's allowed/forbidden)
- Safety constraints (pre-conditions for dangerous actions)
- Standard operating procedures
- Decision frameworks

**Often implemented as:**

1. **Skills** - YAML files defining step-by-step procedures
2. **Policies** - Configuration files or database entries
3. **Instruction files** - System prompts or prompt templates
4. **Code** - Hardcoded behavior for critical safety

**Versioning is critical:**

```python
@dataclass
class SkillVersion:
    skill: Skill
    version: str
    changelog: str
    deprecated: bool = False
    superseded_by: Optional[str] = None

# Track skill evolution
code_review_v1 = SkillVersion(
    skill=code_review_skill,
    version="1.0",
    changelog="Initial version",
    deprecated=False
)

code_review_v2 = SkillVersion(
    skill=code_review_skill_v2,
    version="2.0",
    changelog="Added security vulnerability scanning step",
    deprecated=False
)
```

**Production rules:**

1. **Version control** - Track all changes to skills and policies
2. **Testing** - Test skills before deployment
3. **Auditing** - Log which skills/policies were applied
4. **Hot reload** - Update skills without restarting agent
5. **Conflict detection** - Warn when policies contradict each other

## 4. Memory Operations (CRUD for Agents)

Every memory system must support four fundamental operations. If you don't design all four—especially forgetting—memory becomes a liability instead of an asset.

### 4.1 Write (Store New Information)

**What it does:**

Creates new memory entries when the agent learns something worth remembering.

**Implementation:**

```python
class MemoryWriter:
    """
    Responsible for deciding what to write to memory and how.
    """
    def __init__(
        self,
        long_term_store: LongTermMemoryStore,
        write_policy: WritePolicy
    ):
        self.store = long_term_store
        self.policy = write_policy

    async def consider_writing(
        self,
        content: str,
        context: Dict[str, Any],
        user_id: str
    ) -> Optional[MemoryEntry]:
        """
        Decide whether content is worth storing as long-term memory.
        """
        # 1. Apply write policy filters
        should_write, reason = self.policy.should_write(content, context)
        if not should_write:
            logger.info(f"Not writing to memory: {reason}")
            return None

        # 2. Extract structured memory from content
        memory_entry = await self._extract_memory(content, context, user_id)

        # 3. Check for duplicates or superseding memories
        existing = await self.store.find_similar(
            content=memory_entry.content,
            user_id=user_id,
            threshold=0.9  # High similarity threshold
        )

        if existing:
            # Update confidence instead of creating duplicate
            await self.store.update(
                existing.id,
                {"confidence": max(existing.confidence, memory_entry.confidence)}
            )
            logger.info(f"Updated existing memory {existing.id} instead of creating duplicate")
            return existing

        # 4. Write to long-term memory
        await self.store.store(memory_entry)
        logger.info(f"Wrote new memory: {memory_entry.id}")

        return memory_entry

    async def _extract_memory(
        self,
        content: str,
        context: Dict[str, Any],
        user_id: str
    ) -> MemoryEntry:
        """
        Extract structured memory entry from unstructured content.
        """
        # Use LLM to structure the memory
        prompt = f"""
        Extract a structured memory from this content:
        Content: {content}
        Context: {json.dumps(context)}

        Determine:
        1. Memory type (fact, preference, outcome, constraint)
        2. Confidence level (0.0 to 1.0)
        3. Source (explicit, inferred, learned)
        4. Relevant tags

        Return JSON with these fields.
        """

        structured = await llm.generate(prompt, format="json")

        return MemoryEntry(
            id=f"mem_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            content=content,
            memory_type=structured["memory_type"],
            confidence=structured["confidence"],
            source=structured["source"],
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            access_count=0,
            embedding=await embed(content),
            tags=structured["tags"],
            supersedes=None,
            valid_until=None
        )

@dataclass
class WritePolicy:
    """
    Policy governing what should be written to long-term memory.
    """
    min_confidence: float = 0.7
    require_verification: bool = True
    block_sensitive_data: bool = True

    def should_write(
        self,
        content: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Determine if content should be written to memory.
        """
        # 1. Check confidence
        confidence = context.get("confidence", 0.0)
        if confidence < self.min_confidence:
            return False, f"Confidence {confidence} below threshold {self.min_confidence}"

        # 2. Check for sensitive data
        if self.block_sensitive_data:
            if self._contains_sensitive_data(content):
                return False, "Content contains sensitive data (PII, credentials)"

        # 3. Check for transient information
        transient_markers = [
            "temporarily",
            "just for now",
            "this session only",
            "ephemeral"
        ]
        content_lower = content.lower()
        if any(marker in content_lower for marker in transient_markers):
            return False, "Content marked as transient"

        # 4. Check if this is a stable fact
        if not self._is_stable_fact(content):
            return False, "Content is not a stable fact"

        return True, "Passed all write policy checks"

    def _contains_sensitive_data(self, content: str) -> bool:
        """Check for PII, credentials, etc."""
        # Simple pattern matching (production would use NER + regex)
        sensitive_patterns = [
            r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
            r'\b\d{16}\b',  # Credit card
            r'password[:\s]+\S+',  # Password
            r'api[_-]?key[:\s]+\S+',  # API key
        ]
        for pattern in sensitive_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False

    def _is_stable_fact(self, content: str) -> bool:
        """Check if content represents a stable fact worth remembering."""
        # Facts typically use present tense and declarative form
        # Ephemeral statements use future tense or conditional language
        unstable_markers = ["might", "maybe", "considering", "thinking about"]
        return not any(marker in content.lower() for marker in unstable_markers)
```

**Write rules:**

1. **High confidence required** - Don't store uncertain information
2. **No duplicates** - Check for existing similar memories
3. **Structured extraction** - Convert prose to structured facts
4. **Source attribution** - Always track where memory came from
5. **PII filtering** - Never store sensitive data without consent

### 4.2 Read (Retrieve Relevant Memory)

**What it does:**

Retrieves memories relevant to the current context or query.

**Implementation:**

```python
class MemoryReader:
    """
    Retrieves relevant memories for a given context.
    """
    def __init__(self, long_term_store: LongTermMemoryStore):
        self.store = long_term_store

    async def retrieve_for_task(
        self,
        query: str,
        user_id: str,
        task_type: Optional[str] = None,
        limit: int = 5
    ) -> List[MemoryEntry]:
        """
        Retrieve memories relevant to current task.
        """
        # 1. Build filters based on task type
        filters = {"confidence": {"$gte": 0.7}}
        if task_type:
            filters["tags"] = {"$contains": task_type}

        # 2. Semantic retrieval
        memories = await self.store.retrieve(
            query=query,
            user_id=user_id,
            filters=filters,
            limit=limit
        )

        # 3. Rerank by relevance + recency + access frequency
        ranked_memories = self._rerank(memories, query)

        return ranked_memories[:limit]

    def _rerank(
        self,
        memories: List[MemoryEntry],
        query: str
    ) -> List[MemoryEntry]:
        """
        Rerank memories by composite score.
        """
        scored = []
        for memory in memories:
            # Composite scoring
            score = (
                memory.confidence * 0.5 +  # Confidence is important
                self._recency_score(memory) * 0.3 +  # Recent memories matter
                self._frequency_score(memory) * 0.2  # Frequently accessed matters
            )
            scored.append((score, memory))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [memory for _, memory in scored]

    def _recency_score(self, memory: MemoryEntry) -> float:
        """Score based on how recent the memory is."""
        days_old = (datetime.now() - memory.created_at).days
        # Decay score: 1.0 for today, 0.5 for 30 days ago, 0.1 for 90+ days
        return max(0.1, 1.0 - (days_old / 90.0))

    def _frequency_score(self, memory: MemoryEntry) -> float:
        """Score based on access frequency."""
        # Normalize access count to 0-1 range
        # Assume 50+ accesses is very frequent
        return min(1.0, memory.access_count / 50.0)

    async def retrieve_by_type(
        self,
        user_id: str,
        memory_type: str,
        limit: int = 10
    ) -> List[MemoryEntry]:
        """
        Retrieve all memories of a specific type (e.g., all preferences).
        """
        return await self.store.retrieve(
            query="",  # No semantic query, just filter by type
            user_id=user_id,
            filters={"memory_type": memory_type},
            limit=limit
        )

    async def format_for_prompt(
        self,
        memories: List[MemoryEntry]
    ) -> str:
        """
        Format memories for inclusion in LLM prompt.
        """
        if not memories:
            return ""

        formatted = "## Relevant Context from Memory:\n\n"
        for mem in memories:
            formatted += f"- **{mem.memory_type.title()}**: {mem.content}\n"
            formatted += f"  _Confidence: {mem.confidence:.0%}, Last used: {mem.last_accessed.strftime('%Y-%m-%d')}_\n\n"

        return formatted
```

**Read patterns:**

```python
# Pattern 1: Task-specific retrieval
async def handle_deployment(service_name: str, user_id: str):
    # Retrieve deployment-related memories
    memories = await memory_reader.retrieve_for_task(
        query=f"deploying {service_name}",
        user_id=user_id,
        task_type="deployment"
    )

    # Check for past failures or constraints
    for mem in memories:
        if mem.memory_type == "outcome" and "failed" in mem.content.lower():
            print(f"⚠️  Warning: {mem.content}")

# Pattern 2: Preference retrieval
async def generate_code(task: str, user_id: str):
    # Get user's code style preferences
    preferences = await memory_reader.retrieve_by_type(
        user_id=user_id,
        memory_type="preference"
    )

    # Extract relevant preferences
    language_pref = next(
        (p for p in preferences if "language" in p.tags),
        None
    )

    # Use preferences to guide generation
    if language_pref and "python" in language_pref.content.lower():
        return await generate_python_code(task)
    else:
        return await generate_default_code(task)
```

**Read rules:**

1. **Intent-aware** - Retrieve based on current task, not just keywords
2. **Ranked results** - Consider confidence, recency, and frequency
3. **Limited retrieval** - Don't overwhelm context with too many memories
4. **Type-aware** - Prefer recent preferences, historical outcomes
5. **Formatted for LLM** - Structure memories clearly in prompt

### 4.3 Update (Refine or Overwrite)

**What it does:**

Modifies existing memories when new information refines or corrects previous knowledge.

**Implementation:**

```python
class MemoryUpdater:
    """
    Updates existing memories based on new information.
    """
    def __init__(self, long_term_store: LongTermMemoryStore):
        self.store = long_term_store

    async def update_memory(
        self,
        memory_id: str,
        new_content: Optional[str] = None,
        confidence_delta: Optional[float] = None,
        add_tags: Optional[List[str]] = None
    ):
        """
        Update fields of an existing memory.
        """
        memory = await self.store.get_by_id(memory_id)
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")

        updates = {}

        # Update content if provided
        if new_content:
            updates["content"] = new_content
            updates["embedding"] = await embed(new_content)

        # Update confidence
        if confidence_delta:
            new_confidence = max(0.0, min(1.0, memory.confidence + confidence_delta))
            updates["confidence"] = new_confidence

        # Add tags
        if add_tags:
            updates["tags"] = list(set(memory.tags + add_tags))

        # Apply updates
        await self.store.update(memory_id, updates)

        logger.info(f"Updated memory {memory_id}: {updates.keys()}")

    async def refine_with_feedback(
        self,
        memory_id: str,
        feedback: str,
        user_id: str
    ):
        """
        Refine memory based on user feedback.
        """
        memory = await self.store.get_by_id(memory_id)
        if not memory:
            return

        # Use LLM to integrate feedback
        prompt = f"""
        Original memory: {memory.content}
        User feedback: {feedback}

        Generate refined memory that incorporates the feedback.
        If feedback contradicts the memory, create a corrected version.
        """

        refined_content = await llm.generate(prompt)

        # Create superseding memory
        new_memory = MemoryEntry(
            id=f"mem_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            content=refined_content,
            memory_type=memory.memory_type,
            confidence=0.95,  # High confidence from explicit feedback
            source="explicit",  # User directly corrected
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            access_count=0,
            embedding=await embed(refined_content),
            tags=memory.tags,
            supersedes=memory.id,
            valid_until=None
        )

        await self.store.supersede(memory.id, new_memory)

        logger.info(f"Memory {memory.id} superseded by {new_memory.id} based on user feedback")

    async def adjust_confidence(
        self,
        memory_id: str,
        observation: str,
        adjustment: float
    ):
        """
        Adjust memory confidence based on new observations.
        """
        # Increase confidence when memory proves accurate
        # Decrease confidence when memory is contradicted
        await self.update_memory(
            memory_id=memory_id,
            confidence_delta=adjustment
        )

        logger.info(f"Adjusted confidence of memory {memory_id} by {adjustment:+.2f} due to: {observation}")

    async def merge_memories(
        self,
        memory_ids: List[str],
        user_id: str
    ) -> MemoryEntry:
        """
        Merge multiple related memories into one consolidated memory.
        """
        memories = [await self.store.get_by_id(mid) for mid in memory_ids]
        memories = [m for m in memories if m is not None]

        if not memories:
            raise ValueError("No valid memories to merge")

        # Use LLM to synthesize memories
        prompt = f"""
        Merge these related memories into one consolidated memory:

        {chr(10).join(f"{i+1}. {m.content}" for i, m in enumerate(memories))}

        Generate a single consolidated statement that captures all information.
        """

        merged_content = await llm.generate(prompt)

        # Create merged memory
        merged_memory = MemoryEntry(
            id=f"mem_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            content=merged_content,
            memory_type=memories[0].memory_type,
            confidence=sum(m.confidence for m in memories) / len(memories),
            source="merged",
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            access_count=sum(m.access_count for m in memories),
            embedding=await embed(merged_content),
            tags=list(set(tag for m in memories for tag in m.tags)),
            supersedes=memory_ids[0],  # Mark first as superseded
            valid_until=None
        )

        # Store merged memory
        await self.store.store(merged_memory)

        # Mark old memories as superseded
        for mem in memories:
            await self.store.update(
                mem.id,
                {"valid_until": datetime.now()}
            )

        logger.info(f"Merged {len(memories)} memories into {merged_memory.id}")

        return merged_memory
```

**Update patterns:**

```python
# Pattern 1: Confidence adjustment from outcomes
async def learn_from_outcome(action: str, outcome: str, user_id: str):
    # Find memory that guided this action
    relevant_memories = await memory_reader.retrieve_for_task(
        query=action,
        user_id=user_id
    )

    for memory in relevant_memories:
        if outcome == "success":
            # Memory was correct, increase confidence
            await memory_updater.adjust_confidence(
                memory.id,
                observation=f"Action '{action}' succeeded",
                adjustment=+0.1
            )
        else:
            # Memory was incorrect, decrease confidence
            await memory_updater.adjust_confidence(
                memory.id,
                observation=f"Action '{action}' failed",
                adjustment=-0.2
            )

# Pattern 2: User correction
async def handle_user_correction(memory_id: str, correction: str, user_id: str):
    # User says: "Actually, I prefer TypeScript, not JavaScript"
    await memory_updater.refine_with_feedback(
        memory_id=memory_id,
        feedback=correction,
        user_id=user_id
    )
```

**Update rules:**

1. **Preserve history** - Don't delete old memories, mark as superseded
2. **Track provenance** - Log why memory was updated
3. **Confidence decay** - Decrease confidence when contradicted
4. **Confidence boost** - Increase confidence when confirmed
5. **User corrections** - Treat explicit user feedback as highest confidence

### 4.4 Forget (Delete or Decay)

**What it does:**

Removes or deprioritizes memories that are no longer relevant, incorrect, or outdated.

**This is the most important and most neglected operation.**

**Implementation:**

```python
class MemoryForget:
    """
    Handles forgetting strategies for long-term memory.
    """
    def __init__(
        self,
        long_term_store: LongTermMemoryStore,
        forget_policy: ForgetPolicy
    ):
        self.store = long_term_store
        self.policy = forget_policy

    async def run_forgetting_cycle(self, user_id: str):
        """
        Run periodic forgetting based on policy.
        """
        # 1. Time-based decay
        await self._forget_expired(user_id)

        # 2. Confidence-based pruning
        await self._forget_low_confidence(user_id)

        # 3. Superseded memory cleanup
        await self._cleanup_superseded(user_id)

        # 4. Contradictory memory resolution
        await self._resolve_contradictions(user_id)

        logger.info(f"Completed forgetting cycle for user {user_id}")

    async def _forget_expired(self, user_id: str):
        """Forget memories past their expiration date."""
        expired = await self.store.metadata_db.fetch(
            """
            SELECT id FROM memories
            WHERE user_id = $1
            AND valid_until IS NOT NULL
            AND valid_until < NOW()
            """,
            user_id
        )

        for row in expired:
            await self.forget(row["id"], "Expired (past valid_until date)")

    async def _forget_low_confidence(self, user_id: str):
        """Forget memories that have decayed below confidence threshold."""
        low_confidence = await self.store.metadata_db.fetch(
            """
            SELECT id, confidence FROM memories
            WHERE user_id = $1
            AND confidence < $2
            AND (valid_until IS NULL OR valid_until > NOW())
            """,
            user_id,
            self.policy.min_confidence_threshold
        )

        for row in low_confidence:
            await self.forget(
                row["id"],
                f"Confidence {row['confidence']:.2f} below threshold {self.policy.min_confidence_threshold}"
            )

    async def _cleanup_superseded(self, user_id: str):
        """Remove superseded memories after grace period."""
        # Keep superseded memories for audit trail, but mark for eventual deletion
        grace_days = 90
        old_superseded = await self.store.metadata_db.fetch(
            """
            SELECT id FROM memories
            WHERE user_id = $1
            AND valid_until IS NOT NULL
            AND valid_until < NOW() - INTERVAL '$2 days'
            """,
            user_id,
            grace_days
        )

        for row in old_superseded:
            await self.hard_delete(row["id"], f"Superseded >{ grace_days} days ago")

    async def _resolve_contradictions(self, user_id: str):
        """Find and resolve contradictory memories."""
        # This is complex - requires semantic understanding
        # Simplified: check for memories with opposite sentiments
        all_memories = await self.store.metadata_db.fetch(
            """
            SELECT id, content, confidence FROM memories
            WHERE user_id = $1
            AND (valid_until IS NULL OR valid_until > NOW())
            """,
            user_id
        )

        # Use LLM to detect contradictions
        for i, mem1 in enumerate(all_memories):
            for mem2 in all_memories[i+1:]:
                if await self._are_contradictory(mem1["content"], mem2["content"]):
                    # Keep higher confidence memory, forget lower
                    if mem1["confidence"] > mem2["confidence"]:
                        await self.forget(
                            mem2["id"],
                            f"Contradicts higher-confidence memory {mem1['id']}"
                        )
                    else:
                        await self.forget(
                            mem1["id"],
                            f"Contradicts higher-confidence memory {mem2['id']}"
                        )

    async def _are_contradictory(
        self,
        content1: str,
        content2: str
    ) -> bool:
        """Check if two memory contents contradict each other."""
        prompt = f"""
        Do these two statements contradict each other?
        Statement 1: {content1}
        Statement 2: {content2}

        Answer with only "yes" or "no".
        """
        answer = await llm.generate(prompt)
        return "yes" in answer.lower()

    async def forget(self, memory_id: str, reason: str):
        """Soft delete: mark memory as invalid."""
        await self.store.forget(memory_id, reason)
        logger.info(f"Forgot memory {memory_id}: {reason}")

    async def hard_delete(self, memory_id: str, reason: str):
        """Hard delete: permanently remove memory."""
        await self.store.vector_db.delete(memory_id)
        await self.store.metadata_db.execute(
            "DELETE FROM memories WHERE id = $1",
            memory_id
        )
        await self.store.metadata_db.execute(
            "INSERT INTO memory_deletions (memory_id, reason, deleted_at) VALUES ($1, $2, NOW())",
            memory_id, reason
        )
        logger.info(f"Hard deleted memory {memory_id}: {reason}")

@dataclass
class ForgetPolicy:
    """
    Policy governing when to forget memories.
    """
    min_confidence_threshold: float = 0.3  # Forget below this
    max_age_days: Optional[int] = 365  # Forget older than this
    keep_superseded_days: int = 90  # Keep superseded for audit
    auto_resolve_contradictions: bool = True
```

**Forgetting strategies:**

1. **Time-based decay** - Forget old, rarely accessed memories
2. **Confidence-based pruning** - Remove memories below confidence threshold
3. **Superseding** - Replace old memories with corrected versions
4. **Contradiction resolution** - Remove conflicting memories
5. **Explicit deletion** - User-requested forgetting

**Forgetting rules:**

1. **Audit trail** - Log what was forgotten and why
2. **Grace period** - Don't immediately delete superseded memories
3. **User control** - Allow users to request forgetting
4. **Gradual decay** - Decrease confidence over time, then forget
5. **Privacy compliance** - Enable GDPR-style right to be forgotten

**Critical insight:**

Without forgetting, agents accumulate stale, incorrect, or contradictory knowledge that degrades performance over time. **Forgetting is not a bug—it's a feature.**

## 5. Memory Storage Backends

Production agents use different storage backends optimized for each memory type's characteristics.

### Storage requirements by memory type

| Memory Type | Storage Backend | Rationale |
|-------------|----------------|-----------|
| **Context** | Prompt window | No persistence needed, direct LLM access |
| **Working** | Redis / In-memory | Fast access, automatic TTL, session-scoped |
| **Long-term** | Vector DB + SQL | Semantic search + structured queries |
| **Procedural** | Files / Git | Version controlled, human-editable, code-like |

### 5.1 Context Memory Storage

**Implementation:** Direct prompt construction

```python
class PromptContextManager:
    """
    Manages context memory within prompt window.
    """
    def __init__(self, max_tokens: int = 100_000):
        self.max_tokens = max_tokens
        self.messages: List[Dict[str, str]] = []

    def add_message(self, role: str, content: str):
        """Add message to context."""
        self.messages.append({"role": role, "content": content})
        self._enforce_token_limit()

    def _enforce_token_limit(self):
        """Remove oldest messages if over token limit."""
        while self._count_tokens() > self.max_tokens:
            if len(self.messages) > 1:
                self.messages.pop(0)  # Remove oldest
            else:
                break

    def _count_tokens(self) -> int:
        """Estimate token count."""
        return sum(len(m["content"]) // 4 for m in self.messages)

    def build_prompt(self) -> str:
        """Build full prompt from messages."""
        return "\n\n".join(
            f"{m['role']}: {m['content']}"
            for m in self.messages
        )
```

### 5.2 Working Memory Storage

**Best choice:** Redis with TTL

```python
import redis.asyncio as redis

class RedisWorkingMemory:
    """
    Working memory backed by Redis with automatic expiration.
    """
    def __init__(self, redis_url: str, ttl_seconds: int = 86400):
        self.redis = redis.from_url(redis_url)
        self.ttl = ttl_seconds

    async def save(self, session_id: str, state: Dict[str, Any]):
        """Save session state with TTL."""
        key = f"session:{session_id}"
        await self.redis.setex(
            key,
            self.ttl,
            json.dumps(state, default=str)
        )

    async def load(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session state."""
        key = f"session:{session_id}"
        data = await self.redis.get(key)
        return json.loads(data) if data else None

    async def extend_ttl(self, session_id: str):
        """Extend TTL when session is active."""
        key = f"session:{session_id}"
        await self.redis.expire(key, self.ttl)

    async def clear(self, session_id: str):
        """Clear session state."""
        key = f"session:{session_id}"
        await self.redis.delete(key)
```

**Why Redis:**
- Fast in-memory access
- Built-in TTL (automatic cleanup)
- Persistence optional (can survive restarts)
- Scales horizontally
- Supports atomic operations

### 5.3 Long-Term Memory Storage

**Best choice:** Hybrid Vector DB + SQL

```python
from pinecone import Pinecone
import asyncpg

class HybridLongTermMemory:
    """
    Long-term memory with vector search and structured metadata.
    """
    def __init__(
        self,
        pinecone_api_key: str,
        pinecone_index: str,
        postgres_url: str
    ):
        # Vector storage for semantic search
        self.pinecone = Pinecone(api_key=pinecone_api_key)
        self.index = self.pinecone.Index(pinecone_index)

        # SQL storage for structured queries and metadata
        self.pg_pool = None
        self.postgres_url = postgres_url

    async def initialize(self):
        """Initialize database connections."""
        self.pg_pool = await asyncpg.create_pool(self.postgres_url)

    async def store(self, memory: MemoryEntry):
        """Store memory in both vector and SQL databases."""
        # 1. Store in Pinecone for semantic search
        self.index.upsert(vectors=[
            {
                "id": memory.id,
                "values": memory.embedding,
                "metadata": {
                    "user_id": memory.user_id,
                    "memory_type": memory.memory_type,
                    "confidence": memory.confidence,
                    "tags": ",".join(memory.tags)
                }
            }
        ])

        # 2. Store in Postgres for structured queries
        async with self.pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO memories (
                    id, user_id, content, memory_type, confidence,
                    source, created_at, last_accessed, access_count,
                    tags, supersedes, valid_until
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    confidence = EXCLUDED.confidence,
                    last_accessed = EXCLUDED.last_accessed,
                    access_count = EXCLUDED.access_count
                """,
                memory.id, memory.user_id, memory.content, memory.memory_type,
                memory.confidence, memory.source, memory.created_at,
                memory.last_accessed, memory.access_count, memory.tags,
                memory.supersedes, memory.valid_until
            )

    async def search(
        self,
        query_embedding: List[float],
        user_id: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[MemoryEntry]:
        """Search memories using hybrid approach."""
        # 1. Vector search in Pinecone
        pinecone_filters = {"user_id": user_id}
        if filters:
            pinecone_filters.update(filters)

        vector_results = self.index.query(
            vector=query_embedding,
            filter=pinecone_filters,
            top_k=limit * 2,
            include_metadata=True
        )

        # 2. Fetch full details from Postgres
        memory_ids = [match.id for match in vector_results.matches]

        async with self.pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM memories
                WHERE id = ANY($1)
                AND (valid_until IS NULL OR valid_until > NOW())
                ORDER BY confidence DESC, access_count DESC
                LIMIT $2
                """,
                memory_ids, limit
            )

        return [MemoryEntry(**dict(row)) for row in rows]
```

**Vector DB options:**

1. **Pinecone** - Managed, scalable, easy setup
2. **Weaviate** - Open source, hybrid search built-in
3. **Qdrant** - Fast, supports filtering, open source
4. **Chroma** - Lightweight, good for smaller deployments
5. **Milvus** - High performance, enterprise features

**SQL DB for metadata:**

1. **PostgreSQL** - Best general-purpose choice, supports JSONB, full-text search
2. **MySQL** - Alternative if already in stack
3. **SQLite** - For local/small deployments

### 5.4 Procedural Memory Storage

**Best choice:** Git + Files

```python
from pathlib import Path
import yaml
import git

class FileBasedProceduralMemory:
    """
    Procedural memory stored in version-controlled files.
    """
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.skills_dir = repo_path / "skills"
        self.policies_dir = repo_path / "policies"
        self.repo = git.Repo(repo_path)

    def load_skill(self, skill_name: str) -> Skill:
        """Load skill from YAML file."""
        skill_file = self.skills_dir / f"{skill_name}.yaml"
        with open(skill_file) as f:
            data = yaml.safe_load(f)
        return Skill(**data)

    def save_skill(self, skill: Skill, commit_message: str):
        """Save skill and commit to git."""
        skill_file = self.skills_dir / f"{skill.name}.yaml"
        with open(skill_file, 'w') as f:
            yaml.dump(asdict(skill), f)

        # Git commit
        self.repo.index.add([str(skill_file)])
        self.repo.index.commit(commit_message)

    def list_skills(self) -> List[str]:
        """List all available skills."""
        return [f.stem for f in self.skills_dir.glob("*.yaml")]

    def get_skill_history(self, skill_name: str) -> List[Dict[str, Any]]:
        """Get version history of a skill."""
        skill_file = f"skills/{skill_name}.yaml"
        commits = list(self.repo.iter_commits(paths=skill_file))
        return [
            {
                "commit": c.hexsha[:7],
                "author": str(c.author),
                "date": c.committed_datetime,
                "message": c.message
            }
            for c in commits
        ]
```

**Why files + Git:**
- Version control out of the box
- Human-readable and editable
- Diff and rollback capabilities
- Code review workflows
- Branching for experimentation
- Auditable change history

### 5.5 Production Architecture

```python
class ProductionMemorySystem:
    """
    Complete memory system with all backends.
    """
    def __init__(
        self,
        redis_url: str,
        pinecone_api_key: str,
        postgres_url: str,
        skills_repo_path: Path
    ):
        # Context: managed in prompt
        self.context = PromptContextManager(max_tokens=100_000)

        # Working: Redis
        self.working = RedisWorkingMemory(redis_url, ttl_seconds=86400)

        # Long-term: Pinecone + Postgres
        self.long_term = HybridLongTermMemory(
            pinecone_api_key,
            "agent-memory-index",
            postgres_url
        )

        # Procedural: Git files
        self.procedural = FileBasedProceduralMemory(skills_repo_path)

    async def initialize(self):
        """Initialize all async connections."""
        await self.long_term.initialize()

    async def get_context_for_llm(
        self,
        user_id: str,
        session_id: str,
        query: str
    ) -> str:
        """
        Gather all relevant memory for LLM context.
        """
        # 1. Current conversation (context memory)
        conversation = self.context.build_prompt()

        # 2. Session state (working memory)
        session_state = await self.working.load(session_id)
        working_context = f"\n\n## Current Task State:\n{json.dumps(session_state, indent=2)}" if session_state else ""

        # 3. Relevant long-term memories
        query_embedding = await embed(query)
        long_term_memories = await self.long_term.search(
            query_embedding,
            user_id,
            limit=5
        )
        long_term_context = "\n\n## Relevant Past Knowledge:\n"
        for mem in long_term_memories:
            long_term_context += f"- {mem.content}\n"

        # 4. Applicable skills/policies (procedural memory)
        # (Loaded separately when needed)

        return conversation + working_context + long_term_context
```

**Key architectural principles:**

1. **Separation of concerns** - Each memory type has appropriate storage
2. **Hybrid approach** - Combine strengths of different databases
3. **Scalability** - Each backend can scale independently
4. **Performance** - Right tool for each access pattern
5. **Reliability** - Persistence where needed, ephemeral where appropriate

## 6. Retrieval Strategies (Where Most Systems Fail)

Most agent memory systems fail at retrieval—they either recall too much (overwhelming context), too little (missing critical information), or the wrong things (irrelevant memories).

### 6.1 Similarity-Based Retrieval

**What it is:** Use vector embeddings to find semantically similar memories.

```python
class VectorRetrieval:
    """
    Semantic similarity-based memory retrieval.
    """
    async def retrieve_similar(
        self,
        query: str,
        user_id: str,
        limit: int = 5
    ) -> List[MemoryEntry]:
        """Retrieve memories similar to query."""
        query_embedding = await embed(query)

        results = await vector_db.query(
            vector=query_embedding,
            filter={"user_id": user_id},
            top_k=limit
        )

        return [await self.hydrate_memory(r.id) for r in results]
```

**Good for:**
- User preferences (semantic understanding of "I like X")
- Facts about entities (finding related information)
- Past outcomes (similar situations)

**Fails when:**
- Exact matches needed (e.g., specific constraints)
- Temporal ordering matters
- Relationships are structural, not semantic

### 6.2 Structured Retrieval

**What it is:** Use filters, keys, or graph traversal for deterministic queries.

```python
class StructuredRetrieval:
    """
    Filter-based, deterministic memory retrieval.
    """
    async def retrieve_by_type_and_tags(
        self,
        user_id: str,
        memory_type: str,
        tags: List[str],
        limit: int = 10
    ) -> List[MemoryEntry]:
        """Retrieve memories matching specific criteria."""
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM memories
                WHERE user_id = $1
                AND memory_type = $2
                AND tags && $3
                AND (valid_until IS NULL OR valid_until > NOW())
                ORDER BY confidence DESC, created_at DESC
                LIMIT $4
                """,
                user_id, memory_type, tags, limit
            )

        return [MemoryEntry(**dict(row)) for row in rows]

    async def retrieve_constraints(
        self,
        user_id: str,
        context: Dict[str, Any]
    ) -> List[MemoryEntry]:
        """Retrieve all active constraints."""
        return await self.retrieve_by_type_and_tags(
            user_id,
            memory_type="constraint",
            tags=[],  # All constraints
            limit=100
        )
```

**Good for:**
- Constraints and rules (must be comprehensive, not best-match)
- Policies (need all applicable policies)
- Specific fact lookup (key-based retrieval)

**Fails when:**
- Query is ambiguous or semantic
- Need fuzzy matching
- Don't know exact filters to apply

### 6.3 Hybrid Retrieval (Best Practice)

**What it is:** Combine vector similarity with structured filters and ranking.

```python
class HybridRetrieval:
    """
    Best-of-both-worlds memory retrieval.
    """
    async def retrieve_for_context(
        self,
        query: str,
        user_id: str,
        task_type: Optional[str] = None,
        limit: int = 5
    ) -> List[MemoryEntry]:
        """
        Three-stage hybrid retrieval:
        1. Vector search for candidates
        2. Structured filters to enforce rules
        3. Ranking to select best
        """
        # Stage 1: Vector search (get more candidates)
        query_embedding = await embed(query)
        vector_candidates = await vector_db.query(
            vector=query_embedding,
            filter={"user_id": user_id},
            top_k=limit * 3  # Over-fetch
        )

        # Stage 2: Apply structured filters
        candidate_ids = [c.id for c in vector_candidates]
        async with pg_pool.acquire() as conn:
            filtered = await conn.fetch(
                """
                SELECT * FROM memories
                WHERE id = ANY($1)
                AND (valid_until IS NULL OR valid_until > NOW())
                AND confidence >= 0.7
                """,
                candidate_ids
            )

        memories = [MemoryEntry(**dict(row)) for row in filtered]

        # Stage 3: Rerank by composite score
        ranked = self._rank_memories(memories, query, task_type)

        return ranked[:limit]

    def _rank_memories(
        self,
        memories: List[MemoryEntry],
        query: str,
        task_type: Optional[str]
    ) -> List[MemoryEntry]:
        """
        Rank memories by multiple factors.
        """
        scored = []
        for mem in memories:
            score = 0.0

            # Factor 1: Confidence (40%)
            score += mem.confidence * 0.4

            # Factor 2: Recency (30%)
            days_old = (datetime.now() - mem.created_at).days
            recency_score = max(0.1, 1.0 - (days_old / 90.0))
            score += recency_score * 0.3

            # Factor 3: Access frequency (20%)
            frequency_score = min(1.0, mem.access_count / 50.0)
            score += frequency_score * 0.2

            # Factor 4: Task relevance (10%)
            if task_type and task_type in mem.tags:
                score += 0.1

            scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored]
```

**Production hybrid strategy:**

1. **Vector search** → Find semantically relevant candidates (recall)
2. **Structured filters** → Enforce hard constraints (precision)
3. **Ranking** → Optimize for confidence, recency, relevance (ordering)

**Critical rule:** Memory recall should be intent-aware, not automatic.

## 7. Memory Write Policies (Non-Negotiable)

Agents should not write everything they encounter to memory. **Memory is a commitment—be selective.**

### What to store

**Only store:**

1. **Stable facts**
   - Example: "Service A requires authentication token in X-Auth-Token header"
   - NOT: "I think Service A might need authentication"

2. **Repeated signals**
   - Example: User has corrected "JavaScript" to "TypeScript" three times
   - NOT: User mentioned TypeScript once in passing

3. **Explicit user preferences**
   - Example: "I prefer concise answers without explanations"
   - Source: "explicit" from user statement

4. **Verified outcomes**
   - Example: "Deploying without smoke tests caused 2-hour outage on 2024-03-15"
   - Source: "learned" from actual incident

### What to never store

**Never store:**

1. **Raw conversations** - Store extracted facts, not transcripts
2. **Unverified assumptions** - If confidence < 0.7, don't write
3. **Temporary plans** - Belongs in working memory, not long-term
4. **Sensitive data without consent** - PII, credentials, secrets

### Write policy implementation

```python
WRITE_POLICY = WritePolicy(
    min_confidence=0.7,  # Don't store low-confidence inferences
    require_verification=True,  # Verify facts before storing
    block_sensitive_data=True,  # Filter PII
    max_writes_per_session=10  # Prevent memory spam
)
```

**Production rule:** When in doubt, don't write. It's easier to ask again than to correct wrong memory.

## 8. Memory Update & Correction

Memories must be **mutable**, **versioned**, and **correctable**. Treating memory as immutable truth is a critical mistake.

### Why updates are critical

**Example scenario:**
```
Initial memory: "User prefers short answers"
After 3 interactions: User asks for detailed explanations
Updated memory: "User prefers short answers for simple questions, detailed explanations for complex topics"
```

**Without update capability:**
- Agent continues giving short answers when user wants detail
- User frustration increases
- Trust in agent decreases

**With update capability:**
- Agent refines understanding based on feedback
- Memory becomes more accurate over time
- Agent behavior improves continuously

### Update patterns

```python
# Pattern 1: Confidence adjustment
await memory_updater.adjust_confidence(
    memory_id="mem_abc",
    observation="User confirmed this preference",
    adjustment=+0.15
)

# Pattern 2: Content refinement
await memory_updater.refine_with_feedback(
    memory_id="mem_abc",
    feedback="Actually, I prefer Python 3.11+, not just 'Python'",
    user_id="alice"
)

# Pattern 3: Superseding
await memory_updater.supersede(
    old_memory_id="mem_abc",
    new_memory=refined_memory
)
```

**Never treat memory as immutable truth.** Reality changes, understanding improves, and memory must evolve accordingly.

## 9. Forgetting & Decay (Critical)

**Without forgetting:**
- Agents become brittle (clinging to outdated facts)
- Old facts override new reality
- Errors persist forever
- Memory bloat slows retrieval

### Forgetting strategies

1. **Time-based decay**
   - Reduce confidence of old memories
   - Forget memories older than policy threshold

2. **Confidence thresholds**
   - When confidence drops below 0.3, forget
   - Gradually decrease confidence of unused memories

3. **Explicit invalidation**
   - User says "I don't want you to remember that"
   - Mark memory as invalid immediately

4. **Memory replacement**
   - New memory supersedes old
   - Keep old for audit, but don't retrieve

**Good agents forget intentionally.** Forgetting is not a failure—it's essential for maintaining accurate, relevant knowledge.

## 10. Agent Memory Control Loop

The complete agent control loop with memory integration:

```
┌─────────────────────────────────────────┐
│         Agent Control Loop              │
└─────────────────────────────────────────┘

User Input
    ↓
1. Intent Detection
    "What is the user trying to accomplish?"
    ↓
2. Relevant Memory Retrieval
    Retrieve: preferences, constraints, past outcomes
    ↓
3. Reasoning
    Plan actions considering memory context
    ↓
4. Action
    Execute tools/operations
    ↓
5. Outcome Evaluation
    Did action succeed? What was learned?
    ↓
6. Memory Operations
    - Write new learnings
    - Update existing memories
    - Forget invalidated memories
    ↓
Response to User
```

**Critical insight:** Memory is updated **after** outcomes, not before. Don't store intentions—store results.

## 11. Safety & Privacy

Memory increases risk. Every stored fact is a potential liability.

### Mandatory safeguards

1. **User consent** - Explicit opt-in for long-term memory
2. **PII filtering** - Never store SSN, credit cards, passwords
3. **Encryption at rest** - Encrypt all memory stores
4. **Access controls** - Strict user isolation
5. **Audit logs** - Log all memory writes, reads, deletes

### Never allow

1. **Cross-user memory leaks** - Memories must be strictly scoped to user
2. **Implicit identity inference** - Don't infer user identity from memory
3. **Silent memory accumulation** - User must know what's being remembered

### GDPR compliance

```python
class GDPRCompliantMemory:
    async def export_user_data(self, user_id: str) -> Dict[str, Any]:
        """Export all memories for user (GDPR right to access)."""
        memories = await self.store.get_all_for_user(user_id)
        return {"memories": [asdict(m) for m in memories]}

    async def delete_user_data(self, user_id: str):
        """Delete all memories for user (GDPR right to be forgotten)."""
        await self.store.delete_all_for_user(user_id)
        logger.info(f"Deleted all memories for user {user_id}")
```

## 12. Observability & Debugging

If you can't explain memory behavior, you can't trust it.

### What to log

1. **What memory was retrieved**
   - Which memories were surfaced for each query
   - Retrieval scores and ranking

2. **Why it was selected**
   - Similarity scores
   - Filter criteria that matched
   - Ranking factors

3. **What memory was written**
   - New memory content
   - Confidence and source
   - Why it passed write policy

4. **What memory was ignored**
   - Candidates that didn't make the cut
   - Why they were filtered out

### Logging implementation

```python
class MemoryLogger:
    async def log_retrieval(
        self,
        query: str,
        retrieved: List[MemoryEntry],
        scores: List[float],
        candidates_count: int
    ):
        logger.info({
            "event": "memory_retrieval",
            "query": query,
            "retrieved_count": len(retrieved),
            "candidates_count": candidates_count,
            "top_scores": scores[:3],
            "memory_ids": [m.id for m in retrieved]
        })

    async def log_write(
        self,
        memory: MemoryEntry,
        reason: str
    ):
        logger.info({
            "event": "memory_write",
            "memory_id": memory.id,
            "type": memory.memory_type,
            "confidence": memory.confidence,
            "source": memory.source,
            "reason": reason
        })
```

## 13. Common Failure Modes

Every production incident eventually traces back to memory. Watch for these:

1. **Over-remembering**
   - Storing every utterance
   - Result: Context pollution, slow retrieval

2. **Storing hallucinations**
   - Agent invents fact, stores it as memory
   - Result: Persistent errors, compounding mistakes

3. **No update path**
   - Memory is write-once
   - Result: Cannot correct mistakes, agent stuck with wrong beliefs

4. **Memory pollution**
   - Low-confidence guesses stored as facts
   - Result: Degrading quality over time

5. **Implicit memory writes**
   - Agent writes to memory without user awareness
   - Result: Privacy violations, unexpected behavior

## 14. Reference Production Architecture

```
┌──────────────────────────────────────────────────┐
│                      User                        │
└────────────────────┬─────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────┐
│              Agent Controller                    │
│  - Orchestrates memory and LLM                   │
│  - Enforces safety policies                      │
└────────────────────┬─────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────┐
│              Memory Manager                      │
│                                                  │
│  ┌─────────────┐  ┌─────────────────┐           │
│  │  Context    │  │  Working State  │           │
│  │  (Prompt)   │  │  (Redis)        │           │
│  └─────────────┘  └─────────────────┘           │
│                                                  │
│  ┌─────────────────────────────────────┐        │
│  │  Long-Term Store                    │        │
│  │  (Vector DB + PostgreSQL)           │        │
│  └─────────────────────────────────────┘        │
│                                                  │
│  ┌─────────────────────────────────────┐        │
│  │  Procedural Store                   │        │
│  │  (Git + YAML files)                 │        │
│  └─────────────────────────────────────┘        │
└────────────────────┬─────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────┐
│                    LLM                           │
│  - Receives memory-augmented context             │
│  - Generates responses                           │
└────────────────────┬─────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────┐
│               Tools / Actions                    │
│  - Execute agent actions                         │
│  - Report outcomes to memory manager             │
└──────────────────────────────────────────────────┘
```

**Key principle:** Memory is a first-class system, not an add-on feature.

## 15. When NOT to Use Agent Memory

Avoid long-term memory when:

1. **Tasks are stateless**
   - One-off queries with no context
   - Example: "What's 2+2?"

2. **Sessions are anonymous**
   - No user identity
   - Cannot safely associate memories

3. **Determinism is required**
   - Memory introduces variability
   - Example: Formal verification, compliance checks

4. **Regulatory constraints forbid storage**
   - HIPAA, financial regulations
   - Risk outweighs benefit

**Remember:** Memory is powerful—and costly. Use it when persistence matters, skip it when it doesn't.

---

## Final Takeaway

Agent memory is:

- **Not chat history** - It's structured, governed knowledge
- **Not embeddings alone** - It's a complete CRUD system with policies
- **A governed, intentional system** - Every write, read, update, and forget is deliberate

**Good agents remember what matters, forget what doesn't, and can explain both.**

---

## Learning & Production Resources

### Core Concepts

- Long-term vs short-term agent memory
- Memory write governance and policies
- Memory retrieval strategies (hybrid approach)
- Forgetting mechanisms and decay strategies

### Practical Implementations

- Vector databases for memory recall (Pinecone, Weaviate, Qdrant)
- Graph databases for structured memory (Neo4j)
- Key-value stores for preferences (Redis)
- Hybrid vector + SQL architectures

### Architectures & Patterns

- Agent + memory manager separation
- Read-before-write policies
- Human-in-the-loop memory approval
- Memory operations logging and observability

### Further Reading

- Agent architectures and memory systems
- Retrieval-augmented agents (RAG + memory)
- Long-horizon planning with memory
- Privacy-preserving memory systems