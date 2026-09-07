---
title: "Building Agents with MCP: The Model Context Protocol in Practice"
date: "2026-09-07T11:06:25.900"
draft: false
tags: ["mcp", "model-context-protocol", "ai-agents", "llm", "tool-use"]
description: "A working engineer's guide to building agents with MCP, from protocol fundamentals to production-grade servers, with concrete patterns in Python and TypeScript."
summary: "How to design, build, and ship Model Context Protocol servers that turn LLMs into reliable, tool-using agents — with patterns drawn from Claude Desktop, Cursor, and real production deployments."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-building-agents-with-mcp-the-model-context-protocol-in-practice.svg"
  alt: "Abstract diagram showing an LLM agent connected to multiple MCP servers representing tools like a database, filesystem, and API."
  caption: ""
  relative: false
---

> **TL;DR** — The Model Context Protocol (MCP) is an open standard that lets LLMs discover and call external tools over JSON-RPC. Rather than hand-wiring tool schemas into every agent framework, you implement an MCP server once and any MCP-compatible host (Claude Desktop, Cursor, Zed, Continue) can use it. The real leverage is composition: one server per capability, swappable hosts, and a transport you can scale.

If you've shipped even a toy agent, you've felt the friction: every host has its own way to register tools, every framework reinvents tool schemas, and the moment you want to expose a new capability you write a fresh integration layer. Anthropic open-sourced the [Model Context Protocol](https://modelcontextprotocol.io) in late 2024 to fix that, and a year later it's becoming the de facto standard for connecting models to the outside world.

This post walks through the protocol the way you'd actually use it: what a server and a host are, how the JSON-RPC messages look on the wire, and which patterns hold up when you ship a server that real engineers will depend on.

## Why MCP Exists

Before MCP, the agent tool-calling landscape was a patchwork. OpenAI's function calling, Anthropic's tool use, LangChain's tool abstractions, and a dozen bespoke "agent runtimes" each defined their own schema for describing a tool's name, description, and parameter shape. A Postgres tool you wrote for one client wouldn't port to another without a translation layer.

MCP, as the [spec](https://modelcontextprotocol.io/specification/2025-06-18) describes it, is "a standardized protocol for communication between LLM applications and external tools and data sources." Three things make it different:

1. **A single wire format** (JSON-RPC 2.0) for listing, describing, and invoking tools.
2. **A host/server split** that mirrors the [Language Server Protocol](https://microsoft.github.io/language-server-protocol/) — the agent is the "client," your tool wrapper is the "server."
3. **Capability discovery** — the server tells the host what it offers (`tools`, `resources`, `prompts`) and the host decides what to expose.

The result is that an MCP server you build today works in Claude Desktop today, Cursor tomorrow, and whatever custom runtime your team is prototyping next month.

## The Architecture in One Diagram

Three roles, all defined in the [MCP architecture doc](https://modelcontextprotocol.io/docs/learn/architecture):

- **Host** — the user-facing LLM application (Claude Desktop, Cursor, Zed, Continue). Owns the model, the UI, and the lifecycle.
- **Client** — lives inside the host. Maintains a 1:1 connection to each server, handles the protocol.
- **Server** — your code. Exposes tools, resources, and prompts.

The transport is either `stdio` (the host spawns the server as a subprocess) or `Streamable HTTP` (the server runs as an HTTP service, useful for remote or shared deployments). The classic "local everything" setup uses stdio; production deployments of shared tools almost always use HTTP.

## What's Actually on the Wire

MCP is JSON-RPC 2.0. Three message types matter: `initialize`, the `tools/list` and `tools/call` pair, and the `notifications/initialized` handshake. Here's the handshake a host performs when it boots a server:

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
  "protocolVersion": "2025-06-18",
  "capabilities": {},
  "clientInfo": {"name": "claude-desktop", "version": "1.0.0"}
}}
```

The server replies with its protocol version, capabilities, and `serverInfo`. The host then sends `notifications/initialized` and the session is live. After that, the host can ask the server what tools it has:

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
```

The server returns a list of `Tool` definitions. A `Tool` is a JSON Schema for arguments, a human-readable description, and an optional `annotations` block (read-only, destructive, idempotent — hints the host uses to gate confirmations). When the model decides to use one:

```json
{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
  "name": "get_weather",
  "arguments": {"city": "Berlin"}
}}
```

The server returns either content blocks (`text`, `image`, `audio`, or `resource` links) or a structured error with a JSON-RPC code. That's it. There are no magic tokens, no vendor headers, no opaque binary frames — just structured JSON over a transport.

## Anatomy of an MCP Server

The official SDKs (Python and TypeScript are the most mature, with Go and Rust close behind) take care of JSON-RPC plumbing so you can focus on the tools. A minimal Python server looks like this:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather")

@mcp.tool()
def get_weather(city: str) -> str:
    """Return the current weather for a city."""
    # In real life, call an API
    return f"It's 18°C and clear in {city}."

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

The TypeScript equivalent uses `@modelcontextprotocol/sdk`:

```ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({ name: "weather", version: "1.0.0" });

server.tool(
  "get_weather",
  "Return the current weather for a city.",
  { city: z.string() },
  async ({ city }) => ({
    content: [{ type: "text", text: `It's 18°C and clear in ${city}.` }],
  })
);

const transport = new StdioServerTransport();
await server.connect(transport);
```

Two things are worth noticing. First, the tool function is just a function — the SDK introspects the signature and the docstring to build the JSON Schema and the description the model sees. Second, every tool should have a docstring that doubles as its prompt: the model reads it when deciding whether to call the tool, so vague descriptions produce vague calls.

## Tools, Resources, and Prompts

MCP exposes three kinds of capabilities. They overlap but serve different purposes, as documented in the [server concepts page](https://modelcontextprotocol.io/docs/learn/server-concepts):

- **Tools** are model-controlled actions. The model decides when to call them. `tools/list` and `tools/call` are the lifecycle.
- **Resources** are application-controlled data the host can fetch and stuff into context. They have URIs (`file:///...`, `postgres://...`) and the host decides whether to include them, often via a "mention" UX.
- **Prompts** are user-controlled templates. Slash commands in Claude Desktop are the canonical example.

A well-built server usually exposes all three. A Postgres MCP server, for instance, exposes `query_sql` as a tool, the schema catalog as resources, and a `explain-query` prompt template that pre-fills the model with the right instructions.

> The MCP ecosystem currently lists several thousand servers, with the [official registry](https://github.com/modelcontextprotocol/servers) curating reference implementations for GitHub, Postgres, Slack, the filesystem, and more.

## Patterns in Production

The toy examples above work, but production servers have to survive concurrent users, partial failures, and tools that take minutes rather than milliseconds. Here are the patterns that actually hold up.

### 1. One Server Per Capability, Not Per App

Don't write a "company-internal-tools" server that knows about Postgres, Slack, Jira, and Confluence. Write four servers. Each one is small, easy to audit, and can be enabled or disabled per host. Anthropic's [official servers repo](https://github.com/modelcontextprotocol/servers) follows this convention; community servers that don't usually rot.

### 2. Treat Tool Descriptions Like Prompts

The description string is the model's only specification. Be specific about when to call the tool, what it returns, and what it can't do. Compare:

```text
# Bad
"Get a row from the database."

# Good
"Fetch a single row from the `users` table by primary key. Returns a JSON object
 with `id`, `email`, `created_at`, and `plan`. Use this when the user asks about
 a specific user account. Do NOT use this for listing users — call `list_users`
 with a filter instead."
```

The second one will reliably produce better tool calls. If you find yourself fighting the model to stop using a tool in certain situations, fix the description; don't add logic to suppress calls.

### 3. Annotate Dangerous Tools

MCP lets you tag tools with annotations like `destructiveHint: true` or `readOnlyHint: true`. Hosts can use these to require user confirmation. The [tools spec](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) defines the full set. Any tool that sends mail, charges money, or deletes data should be marked destructive.

### 4. Use Streamable HTTP for Shared Servers

stdio is great for local, single-user setups — it's fast, has no auth surface, and the host manages the lifecycle. For a server that multiple engineers (or multiple agents) need to share, run it over `Streamable HTTP` with proper auth. The [transport spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) describes both modes in detail. A typical deployment: the server listens on an internal port, sits behind an auth proxy, and clients connect by URL.

### 5. Stream Long Results

A tool call can take minutes — think "run this dbt model" or "summarize this 500-page PDF." MCP supports progress notifications (`notifications/progress`) and the streaming content block types described in the [latest spec](https://modelcontextprotocol.io/specification/2025-06-18/server/tools#structured-content). Use them; a tool that silently hangs for two minutes will get cancelled by users.

### 6. Validate Inputs Server-Side

Even though the model produces JSON, never trust it. Validate every argument against your own schema, enforce length limits, and refuse paths that escape a sandbox. A useful pattern: define your tool's parameter schema with a strict JSON Schema (or with Pydantic / Zod) and reject anything that fails validation before it touches your logic.

```python
@mcp.tool()
def read_file(path: str) -> str:
    """Read a file from the project directory."""
    full = (BASE / path).resolve()
    if BASE not in full.parents:
        raise ValueError("Path escapes sandbox")
    return full.read_text()
```

The model is good at escaping sandboxes if you let it.

### 7. Logging Goes to stderr, Not stdout

If you're using stdio, stdout is your wire. The SDKs route logs through stderr by default for exactly this reason. If you write to stdout by accident, the host will try to parse your log line as JSON-RPC and your server will appear to hang.

## An Agent End-to-End

Let's wire a working example: a Postgres MCP server the team can run against a read replica. The goal is that an engineer can open Claude Desktop, ask "how many signups did we get last week broken down by plan?", and get a real answer.

Start with the [reference Postgres server](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres). Install it, point it at your read replica, and configure Claude Desktop via `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "postgres-readonly": {
      "command": "uvx",
      "args": ["mcp-server-postgres", "postgresql://reader@replica/app"]
    }
  }
}
```

Now ask the question. The host sends `tools/list`, the model sees `query_sql`, calls it with the SQL it generated, the server returns the rows, and the model summarizes them. The user sees only the answer; the tool calls show in the UI for transparency.

What's important is that nothing in this flow is proprietary. The same server works in Cursor against the same database with the same query — only the host changed. That's the bet MCP is making, and it's paying off: the [awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) list has grown from a few dozen to thousands in the past year.

## Debugging and Observability

When a tool call goes wrong, you need to see what was actually sent. Three things help:

- **The inspector.** Anthropic ships an [`@modelcontextprotocol/inspector`](https://github.com/modelcontextprotocol/inspector) that connects to your server, lists tools, and lets you hand-fire calls. Run your server under it before you ever attach a host.
- **Wire logging.** Wrap the stdio transport or your HTTP handler with a logger that dumps incoming and outgoing JSON-RPC messages. The Python SDK has this built in via the `--log-level` flag; for TypeScript, a small interceptor on the transport is enough.
- **The host's developer view.** Claude Desktop and Cursor both show tool calls and their results inline. When something fails, the displayed tool name and arguments are the first thing to check.

For deeper observability in production, wrap your server's tool functions with spans and emit OpenTelemetry. The MCP layer is just RPC; treat it like any other service.

## Common Failure Modes

A few things trip up almost everyone the first time:

- **The server appears to hang.** Nine times out of ten you wrote a log line to stdout in stdio mode. Switch it to stderr.
- **The host can't find the server.** Check the absolute path in `claude_desktop_config.json` and make sure the executable is on the host's PATH. `uvx` and `npx` are usually safer bets than system Python.
- **The model hallucinates arguments.** Your tool description is too vague, or your schema is permissive. Tighten both.
- **The model calls a tool you didn't intend.** Add an `annotations` block so the host can gate it, or tighten the description to specify when not to call it.
- **Tool calls time out.** The default timeout in most hosts is generous but finite. If your tool genuinely needs more time, return progress notifications; if it can't complete, return a structured error rather than letting the host kill the process.

## Where MCP Goes From Here

The protocol is moving fast. The June 2025 spec added structured content, async task support, and the Streamable HTTP transport that replaces the older HTTP+SSE pair. The next major releases are focused on registry and discovery — a way for hosts to find and authenticate against public MCP servers without manual configuration, similar to how package managers work today. The [MCP roadmap on GitHub](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions) tracks active discussions.

The bigger architectural shift is that "agent" is becoming a layer rather than an application. A working agent in 2026 is a host (Claude Desktop, Cursor, a custom Slack bot) plugged into a fleet of MCP servers, with the model in the middle orchestrating. The interesting work has moved from "how do I wire my framework's tool calls" to "what capabilities should I expose, and how do I make them safe enough to leave on by default."

## Key Takeaways

- MCP is a JSON-RPC protocol that decouples tool providers from agent hosts, the same way LSP decoupled language tooling from editors.
- A server exposes `tools`, `resources`, and `prompts`; the host discovers them via `tools/list` and invokes them via `tools/call`.
- Use stdio for local, single-user tools and Streamable HTTP for shared or remote ones.
- Tool descriptions double as prompts. Treat them with the same care you'd treat any prompt you'd ship.
- Always validate inputs, annotate destructive tools, stream long-running work, and never log to stdout in stdio mode.
- Build one server per capability, not one mega-server. The composability is the point.

## Further Reading

- [Model Context Protocol — official documentation](https://modelcontextprotocol.io)
- [MCP Specification (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18)
- [Anthropic's announcement of MCP](https://www.anthropic.com/news/model-context-protocol)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP Inspector — a debugger for servers](https://github.com/modelcontextprotocol/inspector)
- [awesome-mcp-servers — community-curated server list](https://github.com/punkpeye/awesome-mcp-servers)