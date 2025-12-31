---
title: "Docker AI Agents & MCP Deep Dive: Zero-to-Production Guide"
date: "2025-12-29T14:00:00+02:00"
draft: false
tags: ["docker", "ai agents", "MCP", "model context protocol", "llm", "javascript", "containers"]
---

## Introduction

The rise of AI agents has created a fundamental challenge: how do you connect dozens of LLMs to hundreds of external tools without writing custom integrations for every combination? This is the "N×M problem"—managing connections between N models and M tools becomes exponentially complex.

The **Model Context Protocol (MCP)** solves this by providing a standardized interface between AI systems and external capabilities. Docker's integration with MCP takes this further by containerizing MCP servers, adding centralized management via the MCP Gateway, and enabling dynamic tool discovery.

### The fundamental problem

| Approach | Connections Needed | Maintenance Burden | Isolation |
|----------|-------------------|-------------------|-----------|
| **Direct Integration** | N × M (every model × every tool) | Exponential | None |
| **MCP Without Docker** | N + M (model + tool) | Linear | Limited |
| **Docker + MCP** | N + M + 1 (via Gateway) | Linear | Full container isolation |

### What Docker + MCP provides

1. **Standardized protocol** - One interface for all LLM-tool communication
2. **Containerized servers** - MCP servers run in isolated Docker containers
3. **Centralized gateway** - Single endpoint manages all MCP server connections
4. **Dynamic discovery** - Agents load only needed tools, reducing token overhead
5. **Verified catalog** - Pre-built, tested MCP servers on Docker Hub
6. **Local model runner** - Run LLMs locally with Docker Model Runner

### When to use Docker + MCP

**Use when:**
- Building AI agents that need external tool access
- Managing multiple MCP servers across different projects
- Requiring strong isolation between tool execution contexts
- Deploying production AI systems with security requirements
- Running local LLMs alongside cloud models

**Skip when:**
- Simple single-tool integration (direct API is simpler)
- No container infrastructure available
- Serverless-only deployment constraints

This guide provides complete implementation details, production patterns, and operational guidance for building reliable Docker-based MCP systems.

---

## 1. Understanding the Model Context Protocol (MCP)

### What is MCP?

The Model Context Protocol is an **open standard** that defines how AI models communicate with external tools, data sources, and services. It enables AI agents to:
- **Perform actions** - Execute tools, call APIs, run code
- **Fetch context** - Retrieve data from databases, search engines, APIs
- **Maintain state** - Persist information across interactions

### The architecture

```
┌──────────────────────────────────────────────┐
│          MCP Client (AI Agent)               │
│  - Claude Desktop                            │
│  - Custom agent application                  │
│  - Cursor IDE                                │
└────────────┬─────────────────────────────────┘
             ↓ MCP Protocol
┌──────────────────────────────────────────────┐
│          MCP Gateway (Docker)                │
│  - Routes requests to servers                │
│  - Manages credentials                       │
│  - Controls access                           │
└────────────┬─────────────────────────────────┘
             ↓
    ┌────────┴────────┬────────────┬──────────┐
    ↓                 ↓            ↓          ↓
┌─────────┐    ┌─────────┐   ┌─────────┐  ┌─────────┐
│  MCP    │    │  MCP    │   │  MCP    │  │  MCP    │
│ Server  │    │ Server  │   │ Server  │  │ Server  │
│ (Search)│    │ (DB)    │   │ (Files) │  │ (API)   │
└─────────┘    └─────────┘   └─────────┘  └─────────┘
```

### Key principles

**1. Client-server model**
- **MCP clients** are AI agents or applications that invoke tools
- **MCP servers** expose capabilities (search, database access, etc.)
- Communication happens over a standardized protocol

**2. Tool abstraction**
- Tools are described with schemas (parameters, return types)
- LLMs understand tool capabilities from schemas
- Execution is delegated to MCP servers

**3. Stateless protocol**
- Each request is independent
- State management happens at application layer
- Servers don't maintain session state

### MCP vs other approaches

| Feature | Direct API Integration | LangChain Tools | MCP |
|---------|----------------------|-----------------|-----|
| **Standardization** | Custom per API | Framework-specific | Universal protocol |
| **Reusability** | Low (1:1 mapping) | Medium (within framework) | High (any MCP client) |
| **Isolation** | None | None | Container-based |
| **Discovery** | Manual configuration | Code-based | Dynamic (with Docker) |
| **Maintenance** | High (N×M integrations) | Medium | Low (N+M) |

---

## 2. Docker's MCP Enhancements

Docker extends MCP with production-ready infrastructure and developer experience improvements.

### 2.1 MCP Catalog & Toolkit

**MCP Catalog:**
- Verified MCP servers hosted on Docker Hub
- Pre-built, tested, containerized tools
- Community-contributed and Docker-official servers

**Examples:**
- `docker/mcp-server-duckduckgo` - Web search
- `docker/mcp-server-github` - GitHub API integration
- `docker/mcp-server-filesystem` - File operations
- `docker/mcp-server-postgres` - Database access

**MCP Toolkit:**
- UI in Docker Desktop for browsing catalog
- One-click server installation
- Configuration management
- Lifecycle control (start, stop, update)

**Key advantage:** No manual Docker configuration needed. Browse, click, use.

### 2.2 MCP Gateway

The MCP Gateway is a **reverse proxy and manager** for MCP servers.

**What it does:**
1. **Centralized routing** - Single endpoint for all MCP servers
2. **Lifecycle management** - Starts/stops servers on demand
3. **Credential management** - Securely stores and injects credentials
4. **Access control** - Enforces permissions per client
5. **Observability** - Logs all tool invocations

**Architecture:**

```typescript
// MCP Gateway architecture
class MCPGateway {
  private servers: Map<string, MCPServer> = new Map();
  private router: RequestRouter;
  private credentialStore: CredentialStore;
  private accessControl: AccessControl;

  async routeRequest(
    clientId: string,
    serverName: string,
    toolName: string,
    params: any
  ): Promise<any> {
    // 1. Check access
    if (!this.accessControl.canAccess(clientId, serverName, toolName)) {
      throw new Error(`Access denied: ${clientId} -> ${serverName}.${toolName}`);
    }

    // 2. Get or start server
    let server = this.servers.get(serverName);
    if (!server) {
      server = await this.startServer(serverName);
      this.servers.set(serverName, server);
    }

    // 3. Inject credentials
    const credentials = this.credentialStore.get(serverName);
    params = { ...params, _credentials: credentials };

    // 4. Invoke tool
    const result = await server.invoke(toolName, params);

    // 5. Log for observability
    this.logInvocation(clientId, serverName, toolName, result);

    return result;
  }

  private async startServer(serverName: string): Promise<MCPServer> {
    // Pull and run Docker container
    await exec(`docker pull ${serverName}`);
    await exec(`docker run -d --name mcp-${serverName} ${serverName}`);

    // Connect to MCP server
    const server = new MCPServer(serverName);
    await server.connect();

    return server;
  }
}
```

**Benefits:**
- Clients don't manage server connections individually
- Credentials never exposed to clients
- All invocations logged centrally
- Servers isolated in containers

### 2.3 Dynamic MCP

Traditional approach: Load all tool descriptions in every prompt.

**Problem:**
```typescript
// BAD: All tools always in context
const prompt = `
Available tools:
1. search(query: string) - Search the web
2. database_query(sql: string) - Query database
3. file_read(path: string) - Read file
4. api_call(endpoint: string, method: string, body: any) - Call API
... (50 more tools)

User: "What's the weather?"
`;

// Result: Wasted tokens, slow inference, potential tool hallucination
```

**Dynamic MCP solution:** Load tools on demand.

```typescript
// GOOD: Load only needed tools
class DynamicMCPClient {
  async processQuery(query: string): Promise<string> {
    // 1. Initial planning without tools
    const plan = await llm.generate(`
      Query: ${query}

      What tools are needed to answer this?
      Return JSON: { tools: ["tool1", "tool2"] }
    `);

    // 2. Load only required tools
    const requiredTools = JSON.parse(plan).tools;
    const toolSchemas = await this.gateway.getToolSchemas(requiredTools);

    // 3. Execute with minimal context
    const result = await llm.generate(`
      Query: ${query}

      Available tools:
      ${JSON.stringify(toolSchemas)}

      Use these tools to answer the query.
    `);

    return result;
  }
}
```

**Benefits:**
- Reduced token usage (10-100x fewer tokens)
- Faster inference
- Lower hallucination risk
- Scales to hundreds of tools

---

## 3. Core Components Deep Dive

### 3.1 MCP Servers

MCP servers are containerized services that expose tools via the MCP protocol.

**Server structure:**

```typescript
// MCP Server interface
interface MCPServer {
  // Metadata
  name: string;
  version: string;
  description: string;

  // Tool definitions
  tools: Tool[];

  // Lifecycle hooks
  initialize(): Promise<void>;
  shutdown(): Promise<void>;

  // Tool invocation
  invoke(toolName: string, params: any): Promise<any>;
}

interface Tool {
  name: string;
  description: string;
  parameters: JSONSchema;
  returns: JSONSchema;
  handler: (params: any) => Promise<any>;
}

// Example: DuckDuckGo search server
class DuckDuckGoMCPServer implements MCPServer {
  name = "duckduckgo";
  version = "1.0.0";
  description = "Web search using DuckDuckGo";

  tools: Tool[] = [
    {
      name: "search",
      description: "Search the web for a query",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "Search query" },
          max_results: { type: "number", default: 10 }
        },
        required: ["query"]
      },
      returns: {
        type: "object",
        properties: {
          results: {
            type: "array",
            items: {
              type: "object",
              properties: {
                title: { type: "string" },
                url: { type: "string" },
                snippet: { type: "string" }
              }
            }
          }
        }
      },
      handler: async (params) => {
        const { query, max_results = 10 } = params;

        // Call DuckDuckGo API
        const response = await fetch(
          `https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json`
        );
        const data = await response.json();

        // Transform to standard format
        return {
          results: data.RelatedTopics.slice(0, max_results).map(topic => ({
            title: topic.Text,
            url: topic.FirstURL,
            snippet: topic.Text
          }))
        };
      }
    }
  ];

  async initialize() {
    console.log("DuckDuckGo MCP server initialized");
  }

  async shutdown() {
    console.log("DuckDuckGo MCP server shutting down");
  }

  async invoke(toolName: string, params: any): Promise<any> {
    const tool = this.tools.find(t => t.name === toolName);
    if (!tool) {
      throw new Error(`Tool not found: ${toolName}`);
    }

    return await tool.handler(params);
  }
}
```

**Dockerfile for MCP server:**

```dockerfile
FROM node:20-alpine

WORKDIR /app

# Copy server code
COPY package*.json ./
RUN npm install

COPY src/ ./src/
COPY tsconfig.json ./

# Build TypeScript
RUN npm run build

# Expose MCP protocol port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=3s \
  CMD node healthcheck.js || exit 1

# Run server
CMD ["node", "dist/server.js"]
```

**docker-compose.yml for local development:**

```yaml
version: '3.8'

services:
  mcp-duckduckgo:
    build: ./mcp-server-duckduckgo
    container_name: mcp-duckduckgo
    ports:
      - "3001:3000"
    environment:
      - MCP_SERVER_NAME=duckduckgo
      - LOG_LEVEL=info
    restart: unless-stopped
    networks:
      - mcp-network

  mcp-postgres:
    build: ./mcp-server-postgres
    container_name: mcp-postgres
    ports:
      - "3002:3000"
    environment:
      - MCP_SERVER_NAME=postgres
      - DATABASE_URL=postgresql://user:pass@db:5432/mydb
    depends_on:
      - db
    restart: unless-stopped
    networks:
      - mcp-network

  mcp-filesystem:
    build: ./mcp-server-filesystem
    container_name: mcp-filesystem
    ports:
      - "3003:3000"
    environment:
      - MCP_SERVER_NAME=filesystem
      - ALLOWED_PATHS=/data
    volumes:
      - ./data:/data:ro
    restart: unless-stopped
    networks:
      - mcp-network

  db:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: pass
      POSTGRES_USER: user
      POSTGRES_DB: mydb
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - mcp-network

networks:
  mcp-network:
    driver: bridge

volumes:
  postgres-data:
```

### 3.2 MCP Clients

MCP clients are applications or agents that invoke MCP servers.

**Client implementation:**

```typescript
class MCPClient {
  private gateway: string;
  private clientId: string;

  constructor(gateway: string, clientId: string) {
    this.gateway = gateway;
    this.clientId = clientId;
  }

  async listAvailableTools(): Promise<Tool[]> {
    const response = await fetch(`${this.gateway}/tools`, {
      headers: {
        'X-Client-ID': this.clientId
      }
    });

    return await response.json();
  }

  async invokeTool(
    serverName: string,
    toolName: string,
    params: any
  ): Promise<any> {
    const response = await fetch(`${this.gateway}/invoke`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Client-ID': this.clientId
      },
      body: JSON.stringify({
        server: serverName,
        tool: toolName,
        params
      })
    });

    if (!response.ok) {
      throw new Error(`Tool invocation failed: ${response.statusText}`);
    }

    return await response.json();
  }
}

// Usage in an AI agent
class AIAgent {
  private llm: LLM;
  private mcpClient: MCPClient;

  constructor(llm: LLM, mcpClient: MCPClient) {
    this.llm = llm;
    this.mcpClient = mcpClient;
  }

  async processQuery(query: string): Promise<string> {
    // 1. Get available tools
    const tools = await this.mcpClient.listAvailableTools();

    // 2. Ask LLM to plan tool usage
    const plan = await this.llm.generate({
      messages: [
        {
          role: "system",
          content: `You are an AI assistant with access to these tools:
${JSON.stringify(tools, null, 2)}

When you need to use a tool, respond with JSON:
{ "action": "use_tool", "server": "...", "tool": "...", "params": {...} }

When you have the final answer, respond with JSON:
{ "action": "respond", "answer": "..." }`
        },
        {
          role: "user",
          content: query
        }
      ]
    });

    const action = JSON.parse(plan);

    // 3. Execute tool if needed
    if (action.action === "use_tool") {
      const toolResult = await this.mcpClient.invokeTool(
        action.server,
        action.tool,
        action.params
      );

      // 4. Generate final response with tool result
      const finalResponse = await this.llm.generate({
        messages: [
          {
            role: "user",
            content: query
          },
          {
            role: "assistant",
            content: plan
          },
          {
            role: "system",
            content: `Tool result: ${JSON.stringify(toolResult)}`
          },
          {
            role: "user",
            content: "Now provide the final answer based on the tool result."
          }
        ]
      });

      return finalResponse;
    }

    return action.answer;
  }
}
```

---

## 4. Setup & Installation

### 4.1 Prerequisites

**System requirements:**
- Docker Desktop 4.30+ (with MCP support)
- 8GB RAM minimum
- 20GB disk space for containers

**Enable MCP Toolkit:**

```bash
# Check Docker version
docker --version
# Should show 4.30.0 or later

# Enable MCP Toolkit in Docker Desktop
# GUI: Settings > Beta Features > Enable MCP Toolkit
# OR via CLI (if available):
docker mcp enable-toolkit
```

### 4.2 Installing MCP Servers

**From Docker Hub catalog:**

```bash
# List available MCP servers
docker mcp server ls

# Search for specific servers
docker mcp server search "github"

# Install a server
docker mcp server install docker/mcp-server-duckduckgo

# Enable the server
docker mcp server enable duckduckgo

# Check status
docker mcp server status duckduckgo
```

**Manual installation:**

```bash
# Pull MCP server image
docker pull docker/mcp-server-duckduckgo:latest

# Run with docker run
docker run -d \
  --name mcp-duckduckgo \
  --network mcp-network \
  -p 3001:3000 \
  docker/mcp-server-duckduckgo:latest

# Verify it's running
docker logs mcp-duckduckgo
```

### 4.3 Starting the MCP Gateway

**Automatic (via Docker Desktop):**

When MCP Toolkit is enabled, the gateway starts automatically.

**Manual start:**

```bash
# Start gateway
docker mcp gateway start

# Check gateway status
docker mcp gateway status

# View gateway logs
docker mcp gateway logs

# Gateway URL (default)
# http://localhost:8080
```

**Gateway configuration:**

```yaml
# ~/.docker/mcp-gateway-config.yaml
gateway:
  port: 8080
  log_level: info

  # Server discovery
  discovery:
    enabled: true
    interval: 30s

  # Access control
  access_control:
    enabled: true
    default_policy: deny

    # Client permissions
    clients:
      claude-desktop:
        allowed_servers: ["duckduckgo", "filesystem"]
        rate_limit: 100/minute

      custom-agent:
        allowed_servers: ["*"]
        rate_limit: 1000/minute

  # Credential storage
  credentials:
    duckduckgo: {}  # No credentials needed
    github:
      api_token: "${GITHUB_TOKEN}"
    postgres:
      connection_string: "${DATABASE_URL}"
```

### 4.4 Connecting Clients

**Claude Desktop:**

```bash
# Connect Claude Desktop to MCP Gateway
docker mcp client connect claude-desktop

# This updates Claude Desktop's configuration at:
# ~/Library/Application Support/Claude/claude_desktop_config.json
```

**Configuration is added:**

```json
{
  "mcpServers": {
    "docker-gateway": {
      "command": "docker",
      "args": ["mcp", "gateway", "connect"],
      "env": {
        "CLIENT_ID": "claude-desktop"
      }
    }
  }
}
```

**Custom application:**

```typescript
// Connect custom MCP client
const client = new MCPClient(
  "http://localhost:8080",
  "my-custom-agent"
);

// List available tools
const tools = await client.listAvailableTools();
console.log("Available tools:", tools);

// Invoke a tool
const result = await client.invokeTool(
  "duckduckgo",
  "search",
  { query: "Docker MCP tutorial" }
);
console.log("Search results:", result);
```

---

## 5. Docker Model Runner

Docker Model Runner enables running LLMs locally as Docker containers with OCI artifact support.

### 5.1 Pulling Models

```bash
# Pull a model (similar to docker pull)
docker model pull ai/gemma2-9b

# List local models
docker model ls

# Inspect model details
docker model inspect ai/gemma2-9b

# Remove a model
docker model rm ai/gemma2-9b
```

### 5.2 Running Models

**Start a model:**

```bash
# Run model with default settings
docker model run ai/gemma2-9b

# Run with GPU support
docker model run --gpus all ai/gemma2-9b

# Run with custom port
docker model run -p 8000:8000 ai/gemma2-9b

# Run with resource limits
docker model run \
  --memory=8g \
  --cpus=4 \
  ai/gemma2-9b
```

**Docker Model Runner exposes OpenAI-compatible API:**

```bash
# Once running, test the API
curl http://localhost:8000/v1/models

# Generate completion
curl http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma2-9b",
    "prompt": "Explain Docker containers in one sentence:",
    "max_tokens": 50
  }'
```

### 5.3 Using Local Models with MCP

```typescript
// Configure agent to use local model
class LocalModelAgent {
  private model: OpenAI;  // OpenAI SDK works with local models
  private mcpClient: MCPClient;

  constructor() {
    // Point to Docker Model Runner
    this.model = new OpenAI({
      baseURL: "http://localhost:8000/v1",
      apiKey: "not-needed"  // Local models don't need auth
    });

    this.mcpClient = new MCPClient(
      "http://localhost:8080",
      "local-agent"
    );
  }

  async processQuery(query: string): Promise<string> {
    // Get available tools
    const tools = await this.mcpClient.listAvailableTools();

    // Use local model for reasoning
    const response = await this.model.chat.completions.create({
      model: "gemma2-9b",
      messages: [
        {
          role: "system",
          content: `Available tools: ${JSON.stringify(tools)}`
        },
        {
          role: "user",
          content: query
        }
      ],
      temperature: 0.7
    });

    return response.choices[0].message.content;
  }
}
```

### 5.4 Model Runner in docker-compose

```yaml
version: '3.8'

services:
  model-runner:
    image: docker/model-runner:latest
    container_name: gemma2-model
    ports:
      - "8000:8000"
    environment:
      - MODEL_NAME=ai/gemma2-9b
      - GPU_ENABLED=true
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - model-cache:/models
    restart: unless-stopped

  mcp-gateway:
    image: docker/mcp-gateway:latest
    container_name: mcp-gateway
    ports:
      - "8080:8080"
    environment:
      - LOG_LEVEL=info
    volumes:
      - gateway-config:/config
    restart: unless-stopped
    depends_on:
      - model-runner

volumes:
  model-cache:
  gateway-config:
```

---

## 6. Code Mode: Programmatic Tool Chaining

Code mode enables agents to generate JavaScript/TypeScript that orchestrates multiple MCP tool invocations within a single execution context.

### 6.1 Why Code Mode?

**Traditional approach:** Multiple LLM calls

```
User: "Search for React tutorials, summarize the top 3, and save to a file"

1. LLM → "Use search tool"
2. Agent → Invokes search → Returns results
3. LLM → "Use summarize tool on result 1"
4. Agent → Invokes summarize → Returns summary
5. LLM → "Use summarize tool on result 2"
... (many more calls)
10. LLM → "Use file write tool"
11. Agent → Invokes file write → Done

Issues:
- 10+ LLM calls
- Slow (seconds per call)
- High token cost
- State management complexity
```

**Code mode approach:** Single execution

```
User: "Search for React tutorials, summarize the top 3, and save to a file"

1. LLM → Generates JavaScript code:
   const results = await mcp.search("React tutorials");
   const summaries = await Promise.all(
     results.slice(0, 3).map(r => mcp.summarize(r.content))
   );
   await mcp.writeFile("summaries.txt", summaries.join("\n\n"));

2. Agent → Executes code in sandbox → Done

Benefits:
- 1 LLM call
- Fast (sub-second execution)
- Lower cost
- Natural control flow (loops, conditionals)
```

### 6.2 Implementation

**MCP Code Runner:**

```typescript
import { VM } from 'vm2';  // Secure JavaScript sandbox

class MCPCodeRunner {
  private mcpClient: MCPClient;
  private vm: VM;

  constructor(mcpClient: MCPClient) {
    this.mcpClient = mcpClient;

    // Create sandboxed VM
    this.vm = new VM({
      timeout: 30000,  // 30s execution limit
      sandbox: {
        mcp: this.createMCPProxy(),
        console: {
          log: (...args) => console.log('[SANDBOX]', ...args)
        }
      }
    });
  }

  private createMCPProxy() {
    // Proxy that routes calls to MCP servers
    return new Proxy({}, {
      get: (target, toolName: string) => {
        return async (...args: any[]) => {
          // Find tool and server
          const tools = await this.mcpClient.listAvailableTools();
          const tool = tools.find(t => t.name === toolName);

          if (!tool) {
            throw new Error(`Tool not found: ${toolName}`);
          }

          // Invoke via MCP
          return await this.mcpClient.invokeTool(
            tool.server,
            toolName,
            args[0]  // First argument is params object
          );
        };
      }
    });
  }

  async execute(code: string): Promise<any> {
    try {
      const result = await this.vm.run(code);
      return { success: true, result };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }
}

// Agent with code mode
class CodeModeAgent {
  private llm: LLM;
  private codeRunner: MCPCodeRunner;

  constructor(llm: LLM, mcpClient: MCPClient) {
    this.llm = llm;
    this.codeRunner = new MCPCodeRunner(mcpClient);
  }

  async processQuery(query: string): Promise<string> {
    // 1. Get available tools
    const tools = await this.codeRunner.mcpClient.listAvailableTools();

    // 2. Generate code
    const code = await this.llm.generate({
      messages: [
        {
          role: "system",
          content: `You are a code generator. Given a user query, generate JavaScript code that uses MCP tools.

Available tools (access via 'mcp' object):
${tools.map(t => `- mcp.${t.name}(${JSON.stringify(t.parameters)})`).join('\n')}

Example:
User: "Search for cats and save results"
Code:
const results = await mcp.search({ query: "cats" });
await mcp.writeFile({ path: "cats.json", content: JSON.stringify(results) });

Generate ONLY executable JavaScript code, no markdown.`
        },
        {
          role: "user",
          content: query
        }
      ]
    });

    // 3. Execute code
    const execution = await this.codeRunner.execute(code);

    if (!execution.success) {
      return `Execution failed: ${execution.error}`;
    }

    // 4. Generate natural language response
    const response = await this.llm.generate({
      messages: [
        {
          role: "user",
          content: query
        },
        {
          role: "assistant",
          content: `Executed: ${code}\nResult: ${JSON.stringify(execution.result)}`
        },
        {
          role: "user",
          content: "Summarize what was done and the result in natural language."
        }
      ]
    });

    return response;
  }
}
```

### 6.3 Code Mode Examples

**Example 1: Multi-step workflow**

```typescript
// User: "Find the top 5 GitHub repos for 'docker' and analyze their stars"

// Generated code:
const repos = await mcp.githubSearch({
  query: "docker",
  sort: "stars",
  limit: 5
});

const analysis = repos.map(repo => ({
  name: repo.name,
  stars: repo.stargazers_count,
  starsPerDay: repo.stargazers_count / repo.age_days
}));

const summary = {
  total_stars: analysis.reduce((sum, r) => sum + r.stars, 0),
  avg_stars_per_day: analysis.reduce((sum, r) => sum + r.starsPerDay, 0) / analysis.length,
  top_repo: analysis[0]
};

return summary;
```

**Example 2: Conditional logic**

```typescript
// User: "Check if the database has users, if not, seed it"

// Generated code:
const count = await mcp.databaseQuery({
  sql: "SELECT COUNT(*) as count FROM users"
});

if (count.rows[0].count === 0) {
  console.log("No users found, seeding database...");

  const users = [
    { name: "Alice", email: "alice@example.com" },
    { name: "Bob", email: "bob@example.com" }
  ];

  for (const user of users) {
    await mcp.databaseQuery({
      sql: "INSERT INTO users (name, email) VALUES ($1, $2)",
      params: [user.name, user.email]
    });
  }

  return `Seeded ${users.length} users`;
} else {
  return `Database already has ${count.rows[0].count} users`;
}
```

**Example 3: Error handling**

```typescript
// User: "Try to fetch user profile, fallback to default if not found"

// Generated code:
let profile;

try {
  profile = await mcp.apiCall({
    url: "https://api.example.com/user/123",
    method: "GET"
  });
} catch (error) {
  console.log("API call failed, using default profile");

  profile = {
    id: 123,
    name: "Guest User",
    email: "guest@example.com"
  };
}

return profile;
```

---

## 7. Production Architecture

### 7.1 Complete Production Setup

```yaml
# docker-compose.prod.yaml
version: '3.8'

services:
  # MCP Gateway (central routing)
  mcp-gateway:
    image: docker/mcp-gateway:latest
    container_name: mcp-gateway
    ports:
      - "8080:8080"
    environment:
      - LOG_LEVEL=info
      - METRICS_ENABLED=true
      - TRACING_ENABLED=true
    volumes:
      - ./gateway-config.yaml:/config/gateway.yaml:ro
      - gateway-logs:/logs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    networks:
      - mcp-network

  # MCP Servers
  mcp-duckduckgo:
    image: docker/mcp-server-duckduckgo:latest
    container_name: mcp-duckduckgo
    environment:
      - MCP_SERVER_NAME=duckduckgo
      - RATE_LIMIT=100/minute
    restart: unless-stopped
    networks:
      - mcp-network

  mcp-github:
    image: docker/mcp-server-github:latest
    container_name: mcp-github
    environment:
      - MCP_SERVER_NAME=github
      - GITHUB_TOKEN=${GITHUB_TOKEN}
    restart: unless-stopped
    networks:
      - mcp-network

  mcp-postgres:
    image: docker/mcp-server-postgres:latest
    container_name: mcp-postgres
    environment:
      - MCP_SERVER_NAME=postgres
      - DATABASE_URL=${DATABASE_URL}
    depends_on:
      - db
    restart: unless-stopped
    networks:
      - mcp-network

  mcp-filesystem:
    image: docker/mcp-server-filesystem:latest
    container_name: mcp-filesystem
    environment:
      - MCP_SERVER_NAME=filesystem
      - ALLOWED_PATHS=/data,/uploads
    volumes:
      - app-data:/data
      - user-uploads:/uploads
    restart: unless-stopped
    networks:
      - mcp-network

  # Local Model Runner
  model-runner:
    image: docker/model-runner:latest
    container_name: local-llm
    ports:
      - "8000:8000"
    environment:
      - MODEL_NAME=ai/llama3.2-3b
      - GPU_ENABLED=true
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - model-cache:/models
    restart: unless-stopped
    networks:
      - mcp-network

  # Supporting services
  db:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_DB: ${DB_NAME}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    restart: unless-stopped
    networks:
      - mcp-network

  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
    restart: unless-stopped
    networks:
      - mcp-network

  # Monitoring
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    restart: unless-stopped
    networks:
      - mcp-network

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
    volumes:
      - grafana-data:/var/lib/grafana
    depends_on:
      - prometheus
    restart: unless-stopped
    networks:
      - mcp-network

networks:
  mcp-network:
    driver: bridge

volumes:
  gateway-logs:
  app-data:
  user-uploads:
  model-cache:
  postgres-data:
  redis-data:
  prometheus-data:
  grafana-data:
```

### 7.2 Security Best Practices

**1. Credential management**

```yaml
# gateway-config.yaml
credentials:
  # Use environment variables, never hardcode
  github:
    api_token: "${GITHUB_TOKEN}"

  postgres:
    connection_string: "${DATABASE_URL}"

  # Encrypt credentials at rest
  encryption:
    enabled: true
    key_file: /secrets/encryption.key
```

**2. Access control**

```yaml
# gateway-config.yaml
access_control:
  enabled: true
  default_policy: deny

  clients:
    production-agent:
      allowed_servers:
        - duckduckgo
        - github
        - postgres
      allowed_tools:
        github: ["search", "get_repo"]  # Restrict to specific tools
        postgres: ["query"]  # No write operations
      rate_limits:
        requests_per_minute: 100
        tokens_per_day: 1000000

    admin-client:
      allowed_servers: ["*"]
      allowed_tools: {"*": ["*"]}
      rate_limits:
        requests_per_minute: 1000
```

**3. Network isolation**

```yaml
# Separate networks for different security zones
networks:
  mcp-public:
    driver: bridge
    # Gateway and public-facing servers

  mcp-internal:
    driver: bridge
    internal: true
    # Database and sensitive servers

  mcp-dmz:
    driver: bridge
    # External API servers
```

**4. Secrets management**

```bash
# Use Docker secrets
echo "${GITHUB_TOKEN}" | docker secret create github_token -
echo "${DATABASE_URL}" | docker secret create db_url -

# Reference in docker-compose
services:
  mcp-github:
    secrets:
      - github_token
    environment:
      - GITHUB_TOKEN_FILE=/run/secrets/github_token
```

### 7.3 Observability

**Logging:**

```typescript
// Structured logging for MCP Gateway
class GatewayLogger {
  logInvocation(
    clientId: string,
    server: string,
    tool: string,
    params: any,
    result: any,
    duration: number
  ) {
    console.log(JSON.stringify({
      timestamp: new Date().toISOString(),
      event: "tool_invocation",
      client_id: clientId,
      server: server,
      tool: tool,
      params: this.sanitizeParams(params),
      result_size: JSON.stringify(result).length,
      duration_ms: duration,
      success: true
    }));
  }

  logError(
    clientId: string,
    server: string,
    tool: string,
    error: Error
  ) {
    console.error(JSON.stringify({
      timestamp: new Date().toISOString(),
      event: "tool_error",
      client_id: clientId,
      server: server,
      tool: tool,
      error: error.message,
      stack: error.stack
    }));
  }

  private sanitizeParams(params: any): any {
    // Remove sensitive data before logging
    const sanitized = { ...params };
    const sensitiveKeys = ['password', 'token', 'api_key', 'secret'];

    for (const key of sensitiveKeys) {
      if (key in sanitized) {
        sanitized[key] = '***REDACTED***';
      }
    }

    return sanitized;
  }
}
```

**Metrics:**

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'mcp-gateway'
    static_configs:
      - targets: ['mcp-gateway:8080']
    metrics_path: '/metrics'
    scrape_interval: 15s

  - job_name: 'mcp-servers'
    static_configs:
      - targets:
        - 'mcp-duckduckgo:3000'
        - 'mcp-github:3000'
        - 'mcp-postgres:3000'
    metrics_path: '/metrics'
    scrape_interval: 30s
```

**Key metrics to track:**

```typescript
// MCP Gateway metrics
interface MCPMetrics {
  // Request metrics
  total_requests: Counter;
  active_requests: Gauge;
  request_duration: Histogram;

  // Tool metrics
  tool_invocations_by_server: Counter;
  tool_invocations_by_client: Counter;
  tool_errors: Counter;

  // Performance metrics
  tool_execution_time: Histogram;
  gateway_routing_time: Histogram;

  // Resource metrics
  active_mcp_servers: Gauge;
  server_memory_usage: Gauge;
  server_cpu_usage: Gauge;
}
```

**Tracing:**

```typescript
// Distributed tracing for MCP calls
import { trace, context } from '@opentelemetry/api';

class TracedMCPGateway {
  private tracer = trace.getTracer('mcp-gateway');

  async routeRequest(
    clientId: string,
    server: string,
    tool: string,
    params: any
  ): Promise<any> {
    return this.tracer.startActiveSpan('mcp.route_request', async (span) => {
      span.setAttribute('client.id', clientId);
      span.setAttribute('server.name', server);
      span.setAttribute('tool.name', tool);

      try {
        const result = await this._routeRequest(clientId, server, tool, params);
        span.setStatus({ code: 0 }); // OK
        return result;
      } catch (error) {
        span.setStatus({ code: 2, message: error.message }); // ERROR
        span.recordException(error);
        throw error;
      } finally {
        span.end();
      }
    });
  }
}
```

---

## 8. Common Failure Modes

### 8.1 Server Unavailability

**Problem:** MCP server container crashes or becomes unresponsive.

**Symptoms:**
- Tool invocations timeout
- Gateway returns 503 errors
- Agents fail to complete tasks

**Solution:**

```yaml
# docker-compose.yaml
services:
  mcp-duckduckgo:
    image: docker/mcp-server-duckduckgo:latest
    restart: unless-stopped  # Auto-restart on failure

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

    deploy:
      replicas: 2  # Run multiple instances
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
```

**Circuit breaker:**

```typescript
class CircuitBreaker {
  private failures = 0;
  private lastFailure: Date | null = null;
  private state: 'closed' | 'open' | 'half-open' = 'closed';

  async invoke(fn: () => Promise<any>): Promise<any> {
    if (this.state === 'open') {
      if (Date.now() - this.lastFailure!.getTime() > 60000) {
        this.state = 'half-open';
      } else {
        throw new Error('Circuit breaker is open');
      }
    }

    try {
      const result = await fn();
      if (this.state === 'half-open') {
        this.state = 'closed';
        this.failures = 0;
      }
      return result;
    } catch (error) {
      this.failures++;
      this.lastFailure = new Date();

      if (this.failures >= 5) {
        this.state = 'open';
      }

      throw error;
    }
  }
}
```

### 8.2 Credential Expiration

**Problem:** API tokens expire, breaking tool access.

**Solution:**

```typescript
class CredentialManager {
  private credentials = new Map<string, Credential>();

  async getCredential(serverName: string): Promise<string> {
    const cred = this.credentials.get(serverName);

    if (!cred) {
      throw new Error(`No credential found for ${serverName}`);
    }

    // Check expiration
    if (cred.expiresAt && cred.expiresAt < new Date()) {
      console.log(`Credential expired for ${serverName}, refreshing...`);
      const newCred = await this.refreshCredential(serverName, cred);
      this.credentials.set(serverName, newCred);
      return newCred.token;
    }

    return cred.token;
  }

  private async refreshCredential(
    serverName: string,
    oldCred: Credential
  ): Promise<Credential> {
    // Call refresh token endpoint
    const response = await fetch(`${serverName}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: oldCred.refreshToken })
    });

    const data = await response.json();

    return {
      token: data.access_token,
      refreshToken: data.refresh_token,
      expiresAt: new Date(Date.now() + data.expires_in * 1000)
    };
  }
}
```

### 8.3 Tool Hallucination

**Problem:** LLM invents tools that don't exist or uses wrong parameters.

**Mitigation:**

```typescript
class SafeMCPClient {
  async invokeTool(
    server: string,
    tool: string,
    params: any
  ): Promise<any> {
    // 1. Validate tool exists
    const availableTools = await this.listAvailableTools();
    const toolDef = availableTools.find(
      t => t.server === server && t.name === tool
    );

    if (!toolDef) {
      throw new Error(
        `Tool not found: ${server}.${tool}\n` +
        `Available tools: ${availableTools.map(t => `${t.server}.${t.name}`).join(', ')}`
      );
    }

    // 2. Validate parameters against schema
    const validation = this.validateParams(params, toolDef.parameters);
    if (!validation.valid) {
      throw new Error(
        `Invalid parameters for ${server}.${tool}:\n` +
        `${validation.errors.join('\n')}`
      );
    }

    // 3. Invoke tool
    return await this._invokeTool(server, tool, params);
  }

  private validateParams(
    params: any,
    schema: JSONSchema
  ): { valid: boolean; errors: string[] } {
    // Use JSON Schema validator
    const ajv = new Ajv();
    const validate = ajv.compile(schema);
    const valid = validate(params);

    return {
      valid,
      errors: validate.errors?.map(e => e.message) || []
    };
  }
}
```

### 8.4 Resource Exhaustion

**Problem:** MCP servers consume too much memory/CPU.

**Solution:**

```yaml
# Set resource limits
services:
  mcp-duckduckgo:
    image: docker/mcp-server-duckduckgo:latest
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 256M

    # OOM kill preference
    oom_kill_disable: false
    oom_score_adj: 500
```

**Rate limiting:**

```typescript
class RateLimiter {
  private requests = new Map<string, number[]>();

  async checkLimit(
    clientId: string,
    limit: number,
    windowMs: number
  ): Promise<boolean> {
    const now = Date.now();
    const requests = this.requests.get(clientId) || [];

    // Remove requests outside window
    const recentRequests = requests.filter(t => t > now - windowMs);

    if (recentRequests.length >= limit) {
      throw new Error(
        `Rate limit exceeded: ${limit} requests per ${windowMs}ms`
      );
    }

    // Add current request
    recentRequests.push(now);
    this.requests.set(clientId, recentRequests);

    return true;
  }
}
```

---

## 9. Testing MCP Systems

### 9.1 Unit Testing MCP Servers

```typescript
// test/mcp-server.test.ts
import { describe, it, expect } from 'vitest';
import { DuckDuckGoMCPServer } from '../src/servers/duckduckgo';

describe('DuckDuckGo MCP Server', () => {
  let server: DuckDuckGoMCPServer;

  beforeEach(() => {
    server = new DuckDuckGoMCPServer();
    await server.initialize();
  });

  afterEach(async () => {
    await server.shutdown();
  });

  it('should search and return results', async () => {
    const result = await server.invoke('search', {
      query: 'docker containers',
      max_results: 5
    });

    expect(result.results).toBeDefined();
    expect(result.results.length).toBeLessThanOrEqual(5);
    expect(result.results[0]).toHaveProperty('title');
    expect(result.results[0]).toHaveProperty('url');
    expect(result.results[0]).toHaveProperty('snippet');
  });

  it('should handle invalid parameters', async () => {
    await expect(
      server.invoke('search', {})  // Missing required 'query'
    ).rejects.toThrow('Missing required parameter: query');
  });

  it('should respect rate limits', async () => {
    // Make 100 requests quickly
    const requests = Array(100).fill(null).map(() =>
      server.invoke('search', { query: 'test' })
    );

    // Some should fail with rate limit error
    const results = await Promise.allSettled(requests);
    const rateLimitErrors = results.filter(
      r => r.status === 'rejected' && r.reason.message.includes('rate limit')
    );

    expect(rateLimitErrors.length).toBeGreaterThan(0);
  });
});
```

### 9.2 Integration Testing

```typescript
// test/mcp-integration.test.ts
import { describe, it, expect } from 'vitest';
import { MCPGateway } from '../src/gateway';
import { MCPClient } from '../src/client';

describe('MCP Gateway Integration', () => {
  let gateway: MCPGateway;
  let client: MCPClient;

  beforeAll(async () => {
    // Start gateway with test servers
    gateway = new MCPGateway({
      port: 8081,
      servers: ['duckduckgo', 'filesystem']
    });
    await gateway.start();

    client = new MCPClient('http://localhost:8081', 'test-client');
  });

  afterAll(async () => {
    await gateway.stop();
  });

  it('should route request through gateway', async () => {
    const result = await client.invokeTool(
      'duckduckgo',
      'search',
      { query: 'docker' }
    );

    expect(result.results).toBeDefined();
    expect(result.results.length).toBeGreaterThan(0);
  });

  it('should enforce access control', async () => {
    const restrictedClient = new MCPClient(
      'http://localhost:8081',
      'restricted-client'
    );

    await expect(
      restrictedClient.invokeTool('filesystem', 'read', { path: '/etc/passwd' })
    ).rejects.toThrow('Access denied');
  });
});
```

### 9.3 End-to-End Testing

```typescript
// test/e2e/agent.test.ts
import { describe, it, expect } from 'vitest';
import { CodeModeAgent } from '../src/agent';

describe('Code Mode Agent E2E', () => {
  let agent: CodeModeAgent;

  beforeAll(() => {
    agent = new CodeModeAgent(
      new MockLLM(),
      new MCPClient('http://localhost:8080', 'test-agent')
    );
  });

  it('should complete multi-step workflow', async () => {
    const result = await agent.processQuery(
      'Search for "Docker MCP" and save the top 3 results to a file'
    );

    // Verify search was performed
    expect(result).toContain('found');

    // Verify file was created
    const fileExists = await fs.exists('results.json');
    expect(fileExists).toBe(true);

    // Verify file content
    const content = await fs.readFile('results.json', 'utf-8');
    const data = JSON.parse(content);
    expect(data.length).toBe(3);
  });

  it('should handle errors gracefully', async () => {
    const result = await agent.processQuery(
      'Read a file that does not exist'
    );

    expect(result).toContain('error');
    expect(result).toContain('file not found');
  });
});
```

---

## 10. Performance Optimization

### 10.1 Caching

```typescript
class CachedMCPGateway extends MCPGateway {
  private cache = new LRUCache<string, any>({
    max: 1000,
    ttl: 1000 * 60 * 5  // 5 minutes
  });

  async routeRequest(
    clientId: string,
    server: string,
    tool: string,
    params: any
  ): Promise<any> {
    // Generate cache key
    const cacheKey = this.getCacheKey(server, tool, params);

    // Check cache
    const cached = this.cache.get(cacheKey);
    if (cached) {
      console.log(`Cache hit: ${cacheKey}`);
      return cached;
    }

    // Execute request
    const result = await super.routeRequest(clientId, server, tool, params);

    // Cache result if tool is cacheable
    if (this.isCacheable(server, tool)) {
      this.cache.set(cacheKey, result);
    }

    return result;
  }

  private getCacheKey(server: string, tool: string, params: any): string {
    return `${server}:${tool}:${JSON.stringify(params)}`;
  }

  private isCacheable(server: string, tool: string): boolean {
    // Only cache read operations
    const cacheableTools = {
      'duckduckgo': ['search'],
      'github': ['get_repo', 'search'],
      'filesystem': ['read']
    };

    return cacheableTools[server]?.includes(tool) || false;
  }
}
```

### 10.2 Connection Pooling

```typescript
class PooledMCPGateway extends MCPGateway {
  private serverPools = new Map<string, ServerPool>();

  async getServer(serverName: string): Promise<MCPServer> {
    let pool = this.serverPools.get(serverName);

    if (!pool) {
      pool = new ServerPool(serverName, {
        min: 2,
        max: 10,
        acquireTimeout: 5000
      });
      this.serverPools.set(serverName, pool);
    }

    return await pool.acquire();
  }

  async releaseServer(serverName: string, server: MCPServer) {
    const pool = this.serverPools.get(serverName);
    if (pool) {
      await pool.release(server);
    }
  }
}

class ServerPool {
  private available: MCPServer[] = [];
  private inUse = new Set<MCPServer>();
  private waiting: Array<(server: MCPServer) => void> = [];

  constructor(
    private serverName: string,
    private options: { min: number; max: number; acquireTimeout: number }
  ) {
    this.initialize();
  }

  private async initialize() {
    // Create minimum number of servers
    for (let i = 0; i < this.options.min; i++) {
      const server = await this.createServer();
      this.available.push(server);
    }
  }

  async acquire(): Promise<MCPServer> {
    // Get from available pool
    if (this.available.length > 0) {
      const server = this.available.pop()!;
      this.inUse.add(server);
      return server;
    }

    // Create new if under max
    if (this.inUse.size < this.options.max) {
      const server = await this.createServer();
      this.inUse.add(server);
      return server;
    }

    // Wait for available server
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('Server acquisition timeout'));
      }, this.options.acquireTimeout);

      this.waiting.push((server) => {
        clearTimeout(timeout);
        resolve(server);
      });
    });
  }

  async release(server: MCPServer) {
    this.inUse.delete(server);

    // Give to waiting client
    if (this.waiting.length > 0) {
      const resolve = this.waiting.shift()!;
      this.inUse.add(server);
      resolve(server);
    } else {
      this.available.push(server);
    }
  }

  private async createServer(): Promise<MCPServer> {
    // Start Docker container and connect
    const containerId = await startMCPServerContainer(this.serverName);
    const server = new MCPServer(this.serverName, containerId);
    await server.connect();
    return server;
  }
}
```

### 10.3 Batching

```typescript
class BatchedMCPClient extends MCPClient {
  private batchQueue: Array<{
    server: string;
    tool: string;
    params: any;
    resolve: (result: any) => void;
    reject: (error: Error) => void;
  }> = [];

  private batchTimeout: NodeJS.Timeout | null = null;

  async invokeTool(
    server: string,
    tool: string,
    params: any
  ): Promise<any> {
    return new Promise((resolve, reject) => {
      // Add to batch queue
      this.batchQueue.push({ server, tool, params, resolve, reject });

      // Schedule batch execution
      if (!this.batchTimeout) {
        this.batchTimeout = setTimeout(() => {
          this.executeBatch();
        }, 50);  // 50ms batching window
      }
    });
  }

  private async executeBatch() {
    const batch = this.batchQueue.splice(0);
    this.batchTimeout = null;

    if (batch.length === 0) return;

    console.log(`Executing batch of ${batch.length} requests`);

    try {
      // Group by server
      const byServer = new Map<string, typeof batch>();
      for (const request of batch) {
        const requests = byServer.get(request.server) || [];
        requests.push(request);
        byServer.set(request.server, requests);
      }

      // Execute in parallel per server
      await Promise.all(
        Array.from(byServer.entries()).map(async ([server, requests]) => {
          const results = await this.executeBatchForServer(server, requests);

          // Resolve individual promises
          for (let i = 0; i < requests.length; i++) {
            requests[i].resolve(results[i]);
          }
        })
      );
    } catch (error) {
      // Reject all on error
      for (const request of batch) {
        request.reject(error as Error);
      }
    }
  }

  private async executeBatchForServer(
    server: string,
    requests: Array<{ tool: string; params: any }>
  ): Promise<any[]> {
    // Call batch endpoint if supported
    const response = await fetch(`${this.gateway}/batch`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Client-ID': this.clientId
      },
      body: JSON.stringify({
        server,
        requests: requests.map(r => ({
          tool: r.tool,
          params: r.params
        }))
      })
    });

    return await response.json();
  }
}
```

---

## 11. When NOT to Use Docker + MCP

Avoid this stack when:

### 11.1 Simple Single-Tool Integration

If you only need one tool, direct API integration is simpler:

```typescript
// Don't use MCP for this:
const result = await mcp.invokeTool('github', 'get_repo', { repo: 'docker/mcp' });

// Just call the API directly:
const result = await fetch('https://api.github.com/repos/docker/mcp');
```

### 11.2 Serverless-Only Deployments

MCP Gateway requires persistent containers. In pure serverless environments (AWS Lambda, Cloudflare Workers), MCP overhead isn't worth it.

**Alternative:** Use serverless-native tool invocation patterns.

### 11.3 Ultra-Low Latency Requirements

MCP adds routing overhead (~10-50ms per call). For sub-10ms latency requirements, use direct integrations.

### 11.4 No Container Infrastructure

If you can't run Docker containers (managed hosting, restricted environments), MCP Gateway won't work.

**Alternative:** Use MCP protocol without Docker Gateway (direct client-server communication).

---

## 12. Resources & Further Reading

### Official Documentation

- [Docker MCP Documentation](https://docs.docker.com/ai/gordon/mcp/)
- [MCP Gateway Guide](https://docs.docker.com/ai/mcp-catalog-and-toolkit/mcp-gateway/)
- [MCP Toolkit & Catalog](https://docs.docker.com/ai/mcp-catalog-and-toolkit/toolkit/)
- [Docker Model Runner](https://www.docker.com/products/model-runner/)

### MCP Servers

- [Docker Hub MCP Catalog](https://hub.docker.com/search?q=mcp-server)
- [Anthropic MCP Servers](https://github.com/anthropics/anthropic-quickstarts/tree/main/mcp)
- [Community MCP Servers](https://github.com/topics/mcp-server)

### Tools & Libraries

- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Docker Compose Examples](https://github.com/docker/awesome-compose)

### Related Concepts

- Model Context Protocol specification
- Tool use in LLMs
- Agent architectures
- Container orchestration patterns
- API gateway patterns

---

## Final Takeaway

Docker + MCP provides a production-ready foundation for building AI agents with external tool access. The key advantages are:

- **Standardization** - One protocol for all tools
- **Isolation** - Containers provide security boundaries
- **Centralization** - Gateway simplifies management
- **Dynamic discovery** - Load only needed tools
- **Local execution** - Run models and tools locally

**Use Docker + MCP when:** Building production AI systems that require reliable, scalable, secure tool access across multiple agents and models.

**Skip it when:** Simple single-tool integrations or serverless-only deployments where the overhead isn't justified.

The combination of standardized protocols, container isolation, and dynamic tool discovery makes Docker + MCP the most robust approach for production AI agent systems today.
