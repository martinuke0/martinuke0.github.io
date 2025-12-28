---
title: "Model Context Protocol (MCP): Zero-to-Production Guide"
date: "2025-12-28T02:10:00+02:00"
draft: false
tags: ["mcp", "llm tools", "ai agents", "context", "tooling", "protocol", "infrastructure"]
---

As large language models become more capable, the challenge shifts from "can they reason?" to "can they act?" The Model Context Protocol (MCP) is Anthropic's answer to this question—a standardized way for LLMs to discover, understand, and safely use tools, data, and actions in the real world.

Before MCP, every AI application required custom integrations, hard-coded tool definitions, and fragile glue code. MCP changes this by providing a universal protocol that any LLM can use to interact with external systems.

**Think of MCP as:**
- **USB-C for AI tools** — one standard interface for everything
- **OpenAPI for LLM reasoning** — machine-readable specifications for capabilities
- **A contract between models and the outside world** — clear boundaries and expectations

This guide will take you from understanding the fundamentals to building production-ready MCP servers.

**Official Resources:**
- [MCP Specification](https://modelcontextprotocol.io)
- [MCP GitHub Repository](https://github.com/modelcontextprotocol)

---

## 1. Why MCP Exists (The Real Problem)

### Before MCP
Tool use in LLM applications looked like this:
- Hard-coded function schemas embedded in prompts
- Prompt-stuffed instructions that were brittle and verbose
- One-off integrations built for each specific model
- Fragile tool calling logic that broke with model updates

### The problems this created

**1. No discoverability**
- Models couldn't learn what tools were available at runtime
- Every new tool required updating prompts and code

**2. No standard lifecycle**
- No consistent way to initialize, validate, or shut down tools
- Error handling was ad-hoc and inconsistent

**3. Tight coupling to specific LLMs**
- Tools written for GPT-4 didn't work with Claude
- Switching models meant rewriting integrations

**4. Unsafe or ambiguous actions**
- Unclear boundaries between what models could and couldn't do
- No standard way to gate dangerous operations

### What MCP fixes

MCP introduces a standardized protocol with:

**1. Standard tool discovery**
- Models can query available tools at runtime
- No hard-coded function lists

**2. Explicit schemas**
- Machine-readable tool definitions
- Clear input/output specifications
- JSON Schema validation

**3. Separation of reasoning vs execution**
- Models decide what to do
- MCP servers execute safely
- Clean boundary between thought and action

**4. Composable, reusable tools**
- Write once, use with any MCP-compatible model
- Tools can be combined and orchestrated
- Easy to version and update independently

### The result

**You write a tool once, and any MCP-aware model can use it.**

This is the same revolutionary shift that USB brought to hardware, or that Docker brought to deployment.

## 2. Core MCP Mental Model

### The architecture (three components)

```
Model  <——>  MCP Client  <——>  MCP Server
```

This simple architecture has three clear roles:

**1. Model** (the brain)
- Decides what action to take
- Chooses which tools to use
- Interprets results
- Examples: Claude, GPT-4, LLaMA

**2. MCP Client** (the translator)
- Translates between model and server
- Manages the protocol conversation
- Handles tool discovery
- Validates schemas
- Examples: Claude Desktop, custom applications

**3. MCP Server** (the executor)
- Exposes tools and resources
- Validates inputs
- Executes actions safely
- Returns structured outputs
- Examples: Filesystem server, database server, API server

### What MCP is NOT

It's crucial to understand what MCP doesn't do:

**NOT a framework**
- MCP doesn't prescribe how to build your application
- It's a protocol layer, not application scaffolding

**NOT an agent system**
- MCP doesn't include planning, memory, or decision loops
- Those are agent concerns, built on top of MCP

**NOT a model API**
- MCP doesn't expose model inference
- It's the opposite—it exposes tools TO models

### What MCP IS

**MCP is a protocol + contract.**

Think of it like HTTP:
- HTTP doesn't care what web framework you use
- HTTP doesn't decide what your website does
- HTTP just standardizes how browsers and servers communicate

Similarly:
- MCP doesn't care what agent framework you use
- MCP doesn't decide what your tools do
- MCP just standardizes how models and tools communicate

## 3. MCP Building Blocks (Deep Dive)

MCP has three core primitives: **Tools**, **Resources**, and **Prompts**.

### 3.1 Tools (Actions)

**Tools are executable actions** that modify state or perform operations.

**Examples:**
- `run_sql_query` — Execute a database query
- `call_api` — Make an HTTP request
- `read_file` — Read from filesystem
- `trigger_deploy` — Start a CI/CD pipeline
- `search_vectors` — Query a vector database
- `send_email` — Send a notification
- `create_ticket` — Create a Jira issue

**Every tool has four required components:**

1. **Name** — Unique identifier (e.g., `get_user_by_id`)
2. **Description** — Human and LLM-readable explanation
3. **Input schema** — JSON Schema defining required/optional parameters
4. **Output schema** — Expected return format

**Tool schema example:**
```json
{
  "name": "get_user_by_id",
  "description": "Fetch user information from the database by their unique ID",
  "inputSchema": {
    "type": "object",
    "properties": {
      "user_id": {
        "type": "string",
        "description": "The unique identifier for the user"
      }
    },
    "required": ["user_id"]
  }
}
```

**Key insight:** The model reads the description and schema to understand when and how to use the tool.

### 3.2 Resources (Context)

**Resources are readable context** (not actions). They provide information but don't modify state.

**Examples:**
- Files (code, configs, logs)
- Database rows (read-only views)
- Documents (PDFs, markdown, wikis)
- API responses (cached data)
- System status (metrics, health checks)

**The distinction:**
```
Tools  → DO things (write, execute, modify)
Resources → INFORM (read, observe, context)
```

**Why the separation?**
- Safety: Resources can't cause damage
- Performance: Resources can be cached aggressively
- Clarity: Models know when they're just reading vs. acting

**Example resource:**
```json
{
  "uri": "file:///app/config.yaml",
  "name": "Application Configuration",
  "description": "Current production configuration file",
  "mimeType": "application/x-yaml"
}
```

### 3.3 Prompts (Templates)

**Prompts are reusable, structured prompt templates** that guide model behavior.

**Types:**
- **System instructions** — Behavior guidelines
- **Task templates** — Pre-built workflows
- **Tool usage guidance** — How to use specific tools
- **Domain knowledge** — Context about the problem space

**Think of prompts as:**
> "A library of pre-written instructions that models can reference"

**Example prompt:**
```json
{
  "name": "code_review_assistant",
  "description": "Guide for performing thorough code reviews",
  "arguments": [
    {
      "name": "language",
      "description": "Programming language",
      "required": true
    }
  ]
}
```

**Why prompts matter:**
- Consistency: Same guidelines across sessions
- Composability: Mix and match prompt templates
- Versioning: Update prompts without changing tools

## 4. MCP Server Architecture (Production-Ready)

### Minimal MCP server structure

```
/server
 ├── tools/
 │    ├── database.py      # Database operations
 │    ├── github.py        # GitHub API tools
 │    └── search.py        # Search capabilities
 ├── resources/
 │    ├── files.py         # File system resources
 │    └── docs.py          # Documentation resources
 ├── prompts/
 │    └── templates.py     # Reusable prompt templates
 ├── server.ts            # Main server (TypeScript)
 └── server.py            # Main server (Python)
```

### Responsibilities of an MCP server

Every MCP server must handle five core responsibilities:

**1. Declare capabilities**
- Advertise available tools, resources, and prompts
- Provide schemas for discovery
- Version your API

**2. Validate inputs**
- Check JSON Schema compliance
- Validate types, ranges, and constraints
- Reject malformed requests early

**3. Execute tools**
- Run the requested action safely
- Handle errors gracefully
- Implement timeouts

**4. Return structured outputs**
- Always return valid JSON
- Include status codes
- Provide error details when things fail

**5. Enforce safety boundaries**
- Implement permission checks
- Rate limit requests
- Audit sensitive operations
- Sandbox execution when possible

### Transport layers

MCP supports three transport mechanisms:

**1. STDIO (Standard Input/Output)**
- **Use case:** Local tools, CLI integration
- **Pros:** Simple, low overhead, easy debugging
- **Cons:** Local only, no remote access

**2. HTTP**
- **Use case:** Remote tools, microservices
- **Pros:** Standard protocol, firewall-friendly, scalable
- **Cons:** Higher latency, stateless

**3. WebSockets**
- **Use case:** Real-time tools, streaming responses
- **Pros:** Bidirectional, low latency, stateful
- **Cons:** More complex, connection management

**Choosing the right transport:**

| Factor | STDIO | HTTP | WebSockets |
|--------|-------|------|------------|
| **Latency** | Lowest | Medium | Low |
| **Remote access** | No | Yes | Yes |
| **Streaming** | Limited | No | Yes |
| **Complexity** | Simple | Medium | High |
| **Security** | Local only | TLS | TLS + auth |

**General guidance:**
- Start with STDIO for prototyping
- Use HTTP for production services
- Use WebSockets for real-time needs

## 5. Tool Design Best Practices (Critical)

Building great MCP tools requires following key design principles.

### 5.1 Atomic tools (single responsibility)

**Bad approach:**
```
deploy_and_notify
  ├── Deploy application
  ├── Run health checks
  ├── Send Slack notification
  └── Update status page
```

**Good approach:**
```
deploy_app              # Deploy only
check_health            # Health check only
send_slack_message      # Notify only
update_status_page      # Status update only
```

**Why atomic tools are better:**
- **Composability:** Models can chain tools in different orders
- **Reusability:** Each tool serves multiple use cases
- **Error handling:** Failures are isolated and clear
- **Testing:** Easier to test individual components

**Key insight:** LLMs compose better than they improvise. Give them building blocks, not Swiss Army knives.

### 5.2 Deterministic outputs (structured data)

**Bad: Ambiguous string responses**
```json
{
  "result": "User created successfully, ID is 12345"
}
```

Problems:
- Model has to parse human text
- No guaranteed structure
- Hard to validate
- Prone to breaking

**Good: Structured JSON responses**
```json
{
  "status": "success",
  "data": {
    "user_id": "12345",
    "created_at": "2025-12-28T02:10:00Z"
  },
  "metadata": {
    "execution_time_ms": 45
  }
}
```

Benefits:
- Machine-readable
- Strongly typed
- Easy to validate
- Consistent structure

**Always include:**
- `status` field (success, error, partial)
- `data` object (the actual result)
- `error` object when applicable (code, message, details)

### 5.3 Safe defaults (security first)

**Principle:** Tools should be read-only by default.

**Read-only first:**
```
list_files          # Safe
read_file           # Safe
search_database     # Safe (read-only)
```

**Destructive operations marked explicitly:**
```
delete_file         # Dangerous flag
write_database      # Requires confirmation
deploy_to_prod      # Multiple safeguards
```

**Implementation strategies:**

**1. Permission tiers:**
```python
class ToolPermission(Enum):
    READ = "read"           # No confirmation needed
    WRITE = "write"         # Confirmation recommended
    DESTRUCTIVE = "destructive"  # Requires explicit approval
```

**2. Confirmation flags:**
```json
{
  "name": "delete_database",
  "dangerous": true,
  "requires_confirmation": true,
  "description": "DESTRUCTIVE: Permanently deletes database"
}
```

**3. Environment gating:**
```python
if tool.is_destructive and env == "production":
    require_manual_approval()
```

**4. Rate limiting:**
```python
@rate_limit(calls_per_minute=10)
def expensive_operation():
    pass
```

## 6. MCP vs Function Calling vs Plugins

How does MCP compare to other tool-use approaches?

| Feature | MCP | Function Calling | Plugins |
|---------|-----|------------------|---------|
| **Standardized** | Yes | No | No |
| **Discoverable** | Yes | No | Partial |
| **Model-agnostic** | Yes | No | No |
| **Tool lifecycle** | Yes | No | No |
| **Production-safe** | Yes | Partial | Partial |
| **Versioning** | Yes | Manual | Manual |
| **Security model** | Built-in | DIY | Varies |
| **Separation of concerns** | Clear | Mixed | Mixed |

### Function Calling (OpenAI, Anthropic)

**What it is:**
- Model-specific feature for calling functions
- Functions defined in prompts or API calls
- No standard protocol

**Limitations:**
- Tightly coupled to specific model APIs
- No discovery mechanism
- Manual schema management
- Switching models = rewriting code

**When to use:**
- Simple, single-model applications
- Prototyping
- When MCP overhead isn't justified

### Plugins (ChatGPT, older systems)

**What it is:**
- Application-specific extensions
- Often uses OpenAPI specs
- Ecosystem fragmentation

**Limitations:**
- No standard interface
- Model-specific implementations
- Limited composability
- Unclear boundaries

**When to use:**
- Existing plugin ecosystems
- When targeting specific platforms

### MCP Advantages

**MCP is the first tool system designed for scale:**

1. **Write once, use everywhere**
   - Same tools work with Claude, GPT-4, local models
   - No model-specific code

2. **Runtime discovery**
   - Models learn available tools dynamically
   - No hard-coded function lists

3. **Clear boundaries**
   - Separation between reasoning (model) and execution (server)
   - Easier to secure and audit

4. **Production-ready**
   - Built-in versioning
   - Transport flexibility
   - Security primitives

5. **Ecosystem benefits**
   - Community can share MCP servers
   - Standardized tooling
   - Easier testing and debugging

## 7. Top Most Useful MCP Tools (Real-World)

Here are the highest-value MCP servers to build or use.

### 7.1 Filesystem MCP

**Use cases:**
- Code analysis and navigation
- Configuration file editing
- Log file inspection
- Documentation browsing

**Example tools:**
```
list_directory     # List files in a directory
read_file          # Read file contents
write_file         # Write/update files
search_files       # Search across files
get_file_info      # Get metadata (size, modified, etc.)
```

**Why it's essential:**
- Grounds LLMs in reality (actual code, not assumptions)
- Enables agent workflows (read, analyze, modify, test)
- Foundation for code assistance tools

**Security note:** Always sandbox file access. Never allow `..` path traversal.

### 7.2 Database MCP (SQL + NoSQL)

**Use cases:**
- Ad-hoc analytics and reporting
- Debugging data issues
- Data validation and quality checks
- Schema exploration

**Example tools:**
```
query_database     # Execute SELECT query
get_schema         # Describe table structure
explain_query      # Get query execution plan
```

**Best practices:**
- **Read-only by default** — no INSERT/UPDATE/DELETE without explicit opt-in
- **Parameterized queries only** — prevent SQL injection
- **Query timeouts** — prevent runaway queries
- **Row limits** — cap result set sizes

**Why it's high ROI:**
- Enables self-service analytics
- Reduces back-and-forth with engineers
- Instant data exploration

### 7.3 GitHub MCP

**Use cases:**
- Pull request reviews and comments
- Issue triage and labeling
- Code search across repositories
- Repository analysis and metrics

**Example tools:**
```
list_pull_requests     # Get PRs for a repo
get_pr_diff            # Get PR changes
comment_on_pr          # Add review comment
search_code            # Search code across repos
get_issue              # Fetch issue details
create_issue           # Create new issue
```

**Why this is one of the highest ROI MCP tools:**
- Automates repetitive code review tasks
- Helps with issue triage at scale
- Enables intelligent code search
- Foundation for AI-powered development workflows

**Implementation tip:** Use GitHub's GraphQL API for efficiency.

### 7.4 Web / HTTP MCP

**Use cases:**
- API aggregation (call multiple services)
- Service monitoring and health checks
- SaaS automation (Stripe, Twilio, etc.)
- Web scraping (with appropriate permissions)

**Example tools:**
```
http_get           # GET request
http_post          # POST request with body
fetch_json_api     # Typed API call
check_endpoint     # Health check
```

**Critical tip:**
> Wrap APIs instead of exposing raw HTTP

**Bad:**
```
http_request(url="https://api.stripe.com/v1/charges", method="POST", ...)
```

**Good:**
```
create_stripe_charge(amount, currency, source)
```

**Why wrapping is better:**
- Type safety
- Business logic validation
- Easier to audit
- Clear intent

### 7.5 Search MCP (Web + Internal)

**Use cases:**
- RAG (Retrieval-Augmented Generation) pipelines
- Fact checking and verification
- Research agents
- Internal knowledge base search

**Example tools:**
```
search_web            # Web search (Google, Bing)
search_documentation  # Internal docs
search_code           # Code search
semantic_search       # Vector similarity search
```

**Often combined with:**
- Vector Database MCP (for embeddings)
- Document MCP (for document retrieval)
- Web MCP (for fetching full content)

**Implementation considerations:**
- Cache results aggressively
- Rate limit external APIs
- Track citation sources
- Consider cost per query

### 7.6 Vector Database MCP

**Use cases:**
- Semantic search
- Long-term memory for agents
- Retrieval-Augmented Generation (RAG)
- Similar document finding

**Example tools:**
```
embed_text          # Create embedding
search_similar      # Find similar vectors
store_embedding     # Save to vector DB
list_collections    # List vector collections
```

**Popular backends:**
- **FAISS** — Facebook's similarity search (local)
- **Pinecone** — Managed vector DB
- **Weaviate** — Open-source vector search
- **Chroma** — Lightweight embeddings database

**Why it matters:**
- Enables memory across conversations
- Powers RAG systems
- Improves answer accuracy with context

**Cost consideration:** Embeddings generation can be expensive at scale.

### 7.7 CI/CD MCP

**Use cases:**
- Triggering builds from natural language
- Running test suites on demand
- Deployment orchestration
- Build failure analysis

**Example tools:**
```
trigger_build      # Start CI pipeline
get_build_status   # Check build status
run_tests          # Execute test suite
deploy_to_env      # Deploy to environment
rollback           # Revert deployment
```

**CRITICAL: Requires strict permissioning**
- Multi-factor auth for prod deployments
- Audit logging for all operations
- Dry-run mode for testing
- Rollback capabilities

**Security model:**
```python
@require_approval(environments=["production"])
@audit_log
@rate_limit(calls_per_hour=5)
def deploy_to_production(service, version):
    # ... deployment logic
```

## 8. MCP + Agents (How They Actually Combine)

**Important:** MCP does not replace agents.

Instead, they work together:

```
Agent = Decision logic (planning, reasoning, memory)
MCP   = Execution layer (tools, actions, data)
```

### The typical agent + MCP flow

```
User Goal
    ↓
┌─────────────────┐
│ Agent Reasoning │  ← Agent framework (LangChain, AutoGPT, custom)
└─────────────────┘
    ↓
Select MCP tool
    ↓
┌─────────────────┐
│  MCP Server     │  ← Execute tool safely
└─────────────────┘
    ↓
Observe result
    ↓
Update state/memory
    ↓
Next action or complete
```

### Example: Research agent

**Goal:** "Analyze our competitors' pricing strategies"

**Agent reasoning:**
1. "I need to gather competitor information"
2. → Uses Search MCP to find competitor websites
3. → Uses Web MCP to fetch pricing pages
4. → Uses Database MCP to store findings
5. → Uses Document MCP to generate report

**MCP's role:**
- Provides the tools (search, fetch, store, generate)
- Ensures safe execution
- Returns structured results

**Agent's role:**
- Decides which tools to use and when
- Interprets results
- Plans next steps
- Maintains context and memory

### Key insight

> Agents think, MCP acts.

This separation makes both more powerful:
- Agents can focus on reasoning
- MCP servers can focus on safe execution
- Both can evolve independently

## 9. Common MCP Anti-Patterns

Avoid these mistakes when building MCP tools:

### 1. One giant "do everything" tool

**Anti-pattern:**
```python
def do_work(action, params):
    if action == "deploy":
        # deploy logic
    elif action == "test":
        # test logic
    elif action == "notify":
        # notify logic
    # ... 50 more actions
```

**Why it's bad:**
- Unclear purpose
- Hard to maintain
- Poor error handling
- Model struggles to use it correctly

**Better:** Break into atomic tools

### 2. Letting models execute shell commands directly

**Anti-pattern:**
```python
def run_command(cmd: str):
    return subprocess.run(cmd, shell=True)
```

**Why it's catastrophically bad:**
- Arbitrary code execution
- No validation
- Security nightmare
- Models will inevitably try `rm -rf /`

**Better:** Whitelist specific commands, wrap in safe functions

### 3. Returning unstructured text

**Anti-pattern:**
```python
return "User 12345 was created successfully"
```

**Why it's bad:**
- Model has to parse text
- Fragile and brittle
- Hard to compose with other tools

**Better:** Always return structured JSON

### 4. No versioning

**Anti-pattern:**
- Change tool schemas without versioning
- Break existing integrations
- No migration path

**Why it's bad:**
- Production systems break unexpectedly
- No way to support old and new simultaneously

**Better:** Version your tools (`get_user_v1`, `get_user_v2`)

### 5. No auth boundaries

**Anti-pattern:**
- All tools available to all users
- No permission checks
- No rate limiting

**Why it's bad:**
- Security breach waiting to happen
- Abuse potential
- No accountability

**Better:** Implement RBAC, audit logs, rate limits

## 10. Security Model (Non-Optional)

Security is not optional for production MCP servers. Here's your checklist:

### Required safeguards

**1. Tool allowlists**
```python
ALLOWED_TOOLS = {
    "read_file",
    "list_directory",
    "search_code"
}

def validate_tool(tool_name):
    if tool_name not in ALLOWED_TOOLS:
        raise PermissionError(f"Tool {tool_name} not allowed")
```

**2. Environment isolation**
```python
# Use Docker containers, VMs, or sandboxes
docker run --rm --read-only --network none \
  --cpus=0.5 --memory=512m \
  mcp-server:latest
```

**3. Input validation**
```python
from jsonschema import validate

def execute_tool(tool_name, params):
    schema = get_tool_schema(tool_name)
    validate(params, schema)  # Throws if invalid
    # ... execute
```

**4. Output filtering**
```python
def sanitize_output(result):
    # Remove sensitive data
    if "password" in result:
        result["password"] = "[REDACTED]"
    return result
```

**5. Audit logging**
```python
def log_tool_execution(user, tool, params, result, error=None):
    log.info({
        "timestamp": now(),
        "user": user,
        "tool": tool,
        "params": hash(params),  # Don't log sensitive data
        "success": error is None,
        "error": str(error) if error else None
    })
```

### The golden rule

**Assume the model will try everything.**

Models are curious, creative, and will test boundaries. Your job is to make it safe for them to explore.

### Defense in depth

Layer multiple security controls:

```
User intent
    ↓
Rate limiting        ← Prevent abuse
    ↓
Authentication       ← Verify identity
    ↓
Authorization        ← Check permissions
    ↓
Input validation     ← Sanitize inputs
    ↓
Sandboxed execution  ← Isolate actions
    ↓
Output filtering     ← Remove sensitive data
    ↓
Audit logging        ← Track everything
```

Don't rely on any single layer.

## Final Chapter — Learning Path & Resources

### Step-by-Step Mastery Plan

#### Phase 1: Conceptual understanding (1-2 days)

**Goals:**
- Understand the difference between tools, resources, and prompts
- Learn the discovery flow (how models find and use tools)
- Grasp the mental model (Model ↔ Client ↔ Server)

**Activities:**
1. Read this guide completely
2. Review the [official MCP specification](https://modelcontextprotocol.io)
3. Study example MCP servers in the wild

**Key question to answer:** Why is MCP better than hard-coded function calling?

#### Phase 2: Build your first server (2-3 days)

**Goals:**
- Write a functional MCP server from scratch
- Implement 3-5 atomic tools
- Handle errors and edge cases

**Recommended first tools:**
1. `get_current_time` — Simple, no external dependencies
2. `calculate` — Takes input, returns structured output
3. `search_files` — Real filesystem interaction

**Frameworks to consider:**
- Python: Use the official MCP Python SDK
- TypeScript: Use the official MCP TypeScript SDK
- Other languages: Implement the JSON-RPC protocol

**Success criteria:** Your MCP server passes all protocol conformance tests

#### Phase 3: Integration (3-5 days)

**Goals:**
- Connect your server to an actual LLM
- Observe tool selection behavior
- Debug misunderstandings

**Integration options:**
1. **Claude Desktop** — Easiest, built-in MCP support
2. **Custom client** — Use MCP client SDK
3. **Agent framework** — Integrate with LangChain/LangGraph

**What to observe:**
- Does the model understand when to use each tool?
- Are your tool descriptions clear enough?
- Are errors handled gracefully?

**Iteration:** Refine descriptions based on model behavior

#### Phase 4: Production readiness (1-2 weeks)

**Goals:**
- Add authentication and authorization
- Implement monitoring and logging
- Version your schemas
- Deploy safely

**Checklist:**
- [ ] Auth: API keys, OAuth, or JWT
- [ ] Rate limiting: Per-user, per-tool
- [ ] Monitoring: Latency, error rates, usage
- [ ] Logging: Audit trail for sensitive operations
- [ ] Versioning: Tool schema versions
- [ ] Testing: Unit tests, integration tests
- [ ] Documentation: API docs, examples
- [ ] Deployment: Docker, Kubernetes, or serverless

### High-Quality MCP Resources

#### Official documentation
- **MCP Specification:** [https://modelcontextprotocol.io](https://modelcontextprotocol.io)
- **MCP GitHub:** [https://github.com/modelcontextprotocol](https://github.com/modelcontextprotocol)
- **Python SDK:** [https://github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- **TypeScript SDK:** [https://github.com/modelcontextprotocol/typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk)

#### Tutorials & examples
- **Anthropic MCP examples:** [https://github.com/anthropics/mcp](https://github.com/anthropics/mcp)
- **Community MCP servers:** [https://github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)
- **Building your first MCP server:** Check official docs for walkthroughs

#### Architecture & integration
- **LangGraph + MCP:** [https://langchain-ai.github.io/langgraph/](https://langchain-ai.github.io/langgraph/)
- **Claude API docs:** [https://docs.anthropic.com](https://docs.anthropic.com)
- **OpenAI tool use:** [https://platform.openai.com/docs](https://platform.openai.com/docs)

#### Production patterns
- **Secure tool execution:** Sandboxing, isolation, least privilege
- **Sandboxed runtimes:** Docker, gVisor, Firecracker
- **Capability-based access control:** Grant minimal necessary permissions
- **Rate limiting strategies:** Token bucket, sliding window
- **Observability:** OpenTelemetry, Prometheus, Grafana

---

## Summary: MCP in production

### What you learned

1. **MCP is a protocol** — not a framework or agent system
2. **Three primitives** — tools (actions), resources (context), prompts (templates)
3. **Atomic tools win** — compose, don't combine
4. **Security is mandatory** — assume models will test boundaries
5. **MCP enables agents** — provides the execution layer for reasoning systems

### When to use MCP

**Good fit:**
- Building tools for multiple LLMs
- Need runtime tool discovery
- Production AI applications
- Agent systems
- Multi-step workflows

**Overkill for:**
- Simple prototypes
- Single-model, single-tool applications
- When function calling is sufficient

### The big picture

MCP is doing for AI tools what USB did for hardware: creating a universal standard that "just works."

As LLMs become more capable, the bottleneck shifts from reasoning to execution. MCP solves the execution problem, letting models safely interact with the real world.

**The future:** Every API, every service, every tool will have an MCP interface. Models will compose them naturally, just as we use APIs today.

**Start building.** The ecosystem is early, and the opportunities are massive.