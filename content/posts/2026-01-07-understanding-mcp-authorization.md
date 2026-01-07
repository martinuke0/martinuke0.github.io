---
title: "Understanding MCP Authorization"
date: "2026-01-07T11:54:53.542"
draft: false
tags: ["MCP", "authorization", "security", "AI-tools", "API"]
---

## Introduction

The Model Context Protocol (MCP) is rapidly becoming a foundational layer for connecting AI models to external tools, data sources, and services in a standardized way. As more powerful capabilities are exposed to models—querying databases, sending emails, acting in SaaS systems—**authorization** becomes a central concern.

This article walks through:

- What MCP is and how resources fit into its design  
- What **link resources** are and why they matter  
- How link resources are typically used to drive **authorization flows**  
- Example patterns for building MCP servers that handle auth securely  
- Best practices and common pitfalls

The goal is to give you a solid mental model for how **MCP authorization with link resources** works in practice, so you can design safer, more capable integrations.

---

## 1. Quick recap: What is MCP?

MCP (Model Context Protocol) is an open protocol for connecting AI models (clients) to external systems (servers) in a predictable, tool-like way.

At a high level:

- **MCP clients** are things that host or interact with models (e.g., AI IDE plugins, desktop apps, web apps, or orchestrators).
- **MCP servers** wrap external capabilities—APIs, databases, file systems, internal tools—and expose them through a standard interface.
- The communication between them is structured around a few core concepts:
  - **Tools** – Operations/actions that can be performed (e.g., `create_ticket`, `run_query`).
  - **Resources** – Data or locations that can be read, written, or listed (e.g., files, documents, external service endpoints).
  - **Prompts** – Reusable prompt templates.
  - **Capabilities** – Permissions/abilities a client has over tools and resources.

From a security standpoint, MCP is explicitly designed so that:

- Servers define **what exists and what can be done**.
- Clients—and ultimately humans—retain **control over what’s allowed and when**.

Authorization is the glue that makes that safe.

---

## 2. Resources in MCP: the foundation

Before focusing on link resources, it helps to understand **resources** in general.

A **resource** in MCP usually has:

- A **URI or identifier** – e.g., `file:///project/app.js`, `db://prod/users`, or a custom scheme.
- Some **capabilities** – e.g., `read`, `write`, `list`.
- Optionally, **parameters** or templates – for dynamic references.
- Descriptive metadata so the model and user understand what it represents.

Conceptually, you can think of a resource as:

> “A thing the model can access or refer to through the MCP server.”

Examples:

- A file resource:
  - `file:///home/user/project/main.py`
- A queryable database resource:
  - `sql://analytics/orders`
- A SaaS object resource:
  - `notion://workspace-123/page/abc123`

In many cases, accessing or modifying a resource requires **authorization**: the client must have valid credentials, tokens, or permissions to act on it.

---

## 3. What are link resources?

**Link resources** are a special category of resources whose main purpose is to expose **clickable links (URLs) to the user**, often to initiate or manage authorization flows.

Instead of being “directly read” by the model like a typical text or file resource, a link resource usually:

- Contains or generates a **URL**.
- Is presented to the **user** (not the model) to open in a browser or in-app web view.
- Often points to:
  - OAuth login/consent screens
  - Device authorization or token exchange pages
  - Connection management dashboards (e.g., “Manage your integrations”)
  - Organization or admin approval flows

Typical use cases:

- **Connect GitHub**:
  - MCP server exposes a link resource `mcp://auth/github` that opens `https://github.com/login/oauth/authorize?...` in the user’s browser.
- **Connect Google Drive**:
  - Link resource directs the user to a Google OAuth consent screen.
- **Connect internal tools**:
  - Link resource opens an internal SSO or approval portal.

The key idea:

> Link resources are the bridge between MCP’s machine-facing protocol and the **human-driven steps** required for safe authorization.

---

## 4. Why authorization needs link resources

In many environments, **authorization cannot be fully automated** by the AI or MCP client:

- OAuth flows require a **browser** and direct interaction with the user.
- Some services require:
  - MFA / 2FA
  - Hardware tokens
  - SSO via corporate identity providers
- Consent screens must be shown to the user for legal or policy reasons.

Yet, the model often needs to say:

> “To perform this action (e.g., access your GitHub repositories), I need you to connect your account.”

Link resources solve this UX and security challenge by:

- Giving the model a **standard, structured handle** to reference the “connect” or “authorize” URL.
- Allowing clients to confidently show the user:
  - What service they are connecting
  - Why the connection is needed
  - What capabilities it will enable
- Keeping **credentials and secrets out of the model context**. The model never sees the access tokens; it only knows that “a connection exists” or “is missing.”

---

## 5. Mental model: authorization workflow with link resources

Here’s a typical end-to-end flow when a user asks the model to do something that requires an external service:

1. **User request**  
   The user asks: “Summarize issues from my private GitHub repository.”

2. **Model reasoning**  
   The model:
   - Knows (via MCP server description) that accessing GitHub requires a connection.
   - Checks whether a valid authorization exists (through tool/resource introspection or server metadata).

3. **Missing authorization**  
   The server indicates:
   - “GitHub is not connected”  
   or  
   - “Token is missing/expired”

4. **Model response to user**  
   The model responds:
   - Explains that GitHub access is required.
   - Refers to a **link resource** like `mcp://auth/github-connect`.

5. **Client action**  
   The MCP client:
   - Recognizes the link resource as something that should be presented to the user.
   - Displays a button or link: “Connect GitHub”.
   - Opening that link triggers an external URL (e.g., OAuth authorization endpoint) in the user’s browser.

6. **User completes auth flow**  
   The user:
   - Signs in
   - Grants permissions
   - Returns with tokens stored securely on the MCP server or a secure storage backend.

7. **Server updates auth state**  
   The MCP server:
   - Stores the access/refresh tokens (or whatever artifacts are needed) securely.
   - Updates its internal state so subsequent calls can use the authorized context.

8. **Retry original operation**  
   The model, now with authorization available:
   - Uses the same tool or resource to access GitHub.
   - Returns the requested result to the user.

Throughout this process, the **model never directly handles passwords or tokens**. The link resource acts as:

- A **safe pointer** to an external human-facing flow.
- A **clear contract** that says, “user needs to do something here for authorization.”

---

## 6. Designing link resources for authorization

How you **structure** link resources is up to your MCP server implementation, but some patterns are emerging.

### 6.1. A simple static link resource

For services with a fixed authorization URL, you might define a static link resource such as:

```jsonc
{
  "name": "github_auth_link",
  "type": "link",
  "description": "Open this link to connect your GitHub account for repository access.",
  "uri": "https://your-auth-service.example.com/github/connect"
}
```

The MCP client can:

- Display the description.
- Present a “Connect GitHub” button that opens the `uri`.

### 6.2. Parameterized link resources

Sometimes, the URL depends on user, tenant, or context parameters. You can expose **templated link resources** that the client or model fills in:

```jsonc
{
  "name": "tenant_oauth_link",
  "type": "link",
  "description": "Use this link to connect the specified tenant via OAuth.",
  "template": {
    "uri": "https://auth.example.com/connect?tenant_id={tenantId}",
    "parameters": [
      {
        "name": "tenantId",
        "description": "Your organization or tenant identifier.",
        "required": true
      }
    ]
  }
}
```

The MCP client can then:

1. Ask the user for `tenantId` (or derive it from configuration).
2. Render the actual URL.
3. Open it in the browser when the user confirms.

### 6.3. Link resources as part of an “auth toolkit”

Many MCP servers group their “connect” steps in an **auth or settings section**, for example:

- `auth/github_connect` (link)
- `auth/google_drive_connect` (link)
- `auth/slack_connect` (link)

The model can:

- Suggest to the user: “You can connect GitHub or Google Drive if you’d like me to access them.”
- Reference the specific link resource when the user chooses a service.

---

## 7. Example: MCP server using link resources for OAuth

To make this more concrete, let’s sketch a simplified MCP server that:

- Exposes tools for working with a hypothetical TODO SaaS: `todo-list`, `todo-add`, etc.
- Requires OAuth to access the user’s TODO account.
- Provides a **link resource** for the user to authorize the connection.

We’ll use TypeScript-style pseudo-code to illustrate the structure. The exact details will vary with your MCP server framework.

### 7.1. Server capabilities and resource description

```ts
// mcp-server.ts (simplified)
import { createMcpServer } from "your-mcp-framework";

const server = createMcpServer({
  name: "todo-service",
  description: "Access and manage tasks in your TODO SaaS account.",
});

// In-memory token store just for example (use something persistent & secure)
const userTokens = new Map<string, string>(); // userId -> accessToken

// Expose a link resource for authorization
server.addResource({
  name: "todo_auth_link",
  type: "link",
  description: "Connect your TODO account to allow the assistant to read and manage your tasks.",
  getUri: async (context) => {
    // context may include information like userId, sessionId, etc.
    const { userId } = context;
    const state = encodeURIComponent(userId);
    // This would be your OAuth authorization URL
    return `https://auth.todo.example.com/oauth/authorize?client_id=XYZ&redirect_uri=https%3A%2F%2Fyour-mcp-server.example.com%2Foauth%2Fcallback&response_type=code&state=${state}`;
  },
});
```

### 7.2. Tools that depend on authorization

```ts
// Check authorization helper
async function requireAuth(userId: string): Promise<string> {
  const token = userTokens.get(userId);
  if (!token) {
    throw new Error(
      "AUTH_REQUIRED: Your TODO account is not connected. Please open the 'todo_auth_link' resource to connect your account."
    );
  }
  return token;
}

server.addTool({
  name: "todo-list",
  description: "List your TODO items from the TODO SaaS.",
  inputSchema: {
    type: "object",
    properties: {
      limit: { type: "number", description: "Maximum number of items to return", default: 20 }
    }
  },
  handler: async ({ input, context }) => {
    const { userId } = context;
    const token = await requireAuth(userId);

    // Call external API
    const response = await fetch("https://api.todo.example.com/v1/tasks?limit=" + (input.limit ?? 20), {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!response.ok) {
      if (response.status === 401) {
        // Token expired or revoked
        userTokens.delete(userId);
        throw new Error(
          "AUTH_EXPIRED: Your TODO authorization has expired. Please re-open the 'todo_auth_link' resource to reconnect."
        );
      }
      throw new Error(`TODO_API_ERROR: ${response.statusText}`);
    }

    const tasks = await response.json();
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(tasks, null, 2),
        }
      ]
    };
  },
});
```

### 7.3. Handling the OAuth callback

Your MCP server (or an attached web service) must handle the OAuth redirect:

```ts
import express from "express";

const app = express();

app.get("/oauth/callback", async (req, res) => {
  const { code, state } = req.query;
  if (!code || !state) {
    return res.status(400).send("Missing code or state");
  }

  const userId = decodeURIComponent(state as string);

  // Exchange code for token
  const tokenResponse = await fetch("https://auth.todo.example.com/oauth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code: code as string,
      redirect_uri: "https://your-mcp-server.example.com/oauth/callback",
      client_id: "XYZ",
      client_secret: process.env.TODO_CLIENT_SECRET!,
    }),
  });

  if (!tokenResponse.ok) {
    console.error("Token exchange failed", await tokenResponse.text());
    return res.status(500).send("Failed to complete authorization.");
  }

  const data = await tokenResponse.json();
  const accessToken = data.access_token as string;

  // Store token securely
  userTokens.set(userId, accessToken);

  // Inform user
  res.send("Your TODO account is now connected. You can return to your AI assistant.");
});

// Start HTTP server for OAuth callbacks
app.listen(8080, () => {
  console.log("OAuth callback server listening on port 8080");
});
```

In this design:

- The **link resource** `todo_auth_link` produces the URL that starts the OAuth flow.
- The user completes the flow in their browser.
- The token is stored in the server-side `userTokens`.
- The tools (`todo-list`, etc.) check `requireAuth` and instruct the user to use the link resource if auth is missing or expired.

From the model’s perspective, the narrative is:

> “I attempted to use the TODO tool but you are not authorized. Please use the `todo_auth_link` resource to connect your account, and then I can continue.”

---

## 8. Security and privacy considerations

Handling authorization—especially across AI and automation—demands careful security design. While MCP and link resources help by **separating** human auth from model logic, you still need to follow best practices.

### 8.1. Never expose secrets to the model

- Do **not** include access tokens, refresh tokens, or API keys in:
  - Tool invocation outputs
  - Resource contents
  - Error messages
- If you must reference them in logs, redact or hash them.

The model only needs to know:

- Whether a connection exists
- Whether it’s valid
- Which **scopes or capabilities** are available (in human-readable form)

### 8.2. Use short-lived tokens and refresh mechanisms

Whenever possible:

- Use **short-lived access tokens** combined with refresh tokens or backend session mechanisms.
- Store refresh tokens securely (e.g., encrypted at rest, access controlled).
- Handle token revocation and rotation gracefully.

This limits the blast radius if a token is ever compromised.

### 8.3. Bind tokens to user identity

MCP often operates in **multi-user** or **multi-session** environments. You should:

- Associate tokens with a specific user, workspace, or tenant:
  - e.g., `userTokens.set(userId, accessToken)`
- Ensure that requests on behalf of user A cannot use tokens from user B.
- Validate that the `state` parameter in OAuth flows is tied to the correct user/session to prevent CSRF and mix-ups.

### 8.4. Clear and minimal scopes

When designing your link resources and auth flows, consider:

- Requesting the **minimal set of scopes** needed to fulfill model actions.
- Exposing these scopes in human-friendly descriptions, e.g.:

  > “This connection lets the assistant read and update your TODO items. It cannot delete your account or modify billing.”

- Allowing users (or admins) to see and revoke connections.

### 8.5. Don’t auto-trigger auth links

Clients should avoid auto-opening or silently triggering auth links. Instead:

- Always require **explicit user action** (e.g., clicking “Connect GitHub”).
- Clearly label where the link goes and what will happen.

This maintains user trust and prevents surprises like auto-login or unwanted account linking.

---

## 9. UX patterns for clients: presenting link resources

MCP clients (e.g., desktop apps, IDE plugins) are the ones that surface link resources to users. Good UX around these links makes authorization **understandable and safe**.

Here are some patterns that work well:

### 9.1. Inline suggestions from the assistant

When the model detects missing authorization, it can respond like:

> “To access your private GitHub repositories, I need you to connect GitHub. Please click the **Connect GitHub** button below, then let me know when you’re done.”

The client should:

- Detect the reference to the `github_auth_link` resource.
- Render a UI element (button, link) associated with that resource.
- Open the corresponding URL in a browser when clicked.

### 9.2. A dedicated “Connections” or “Integrations” panel

Beyond inline prompts, many users expect:

- A **settings page** where they can manage all active connections.
- Visibility into:
  - Which services are connected
  - When connections were last used
  - Options to disconnect or re-authorize

Clients can use link resources (and perhaps additional management tools) to:

- Initiate new connections (“Connect GitHub”, “Connect Slack”).
- Re-run flows when tokens expire.
- Open external account management pages.

### 9.3. Feedback on connection status

After a user completes an auth flow in the browser, clients should:

- Detect that the connection is now valid (e.g., by:
  - Calling a “check-connection” tool, or
  - Being notified via some subscription mechanism).
- Update UI to show:
  - “Connected to GitHub as alice.”
  - Or “Connection failed. Please try again.”

This closes the loop and assures users their action worked.

---

## 10. Common pitfalls and how to avoid them

When implementing MCP authorization with link resources, several recurring issues show up. Here’s how to avoid them.

### 10.1. Pitfall: Leaking URLs with embedded secrets

Some services historically provided “magic links” containing tokens or secrets directly in the URL. Avoid that in MCP:

- Do not embed access tokens or API keys in link resource URLs.
- If the service forces this pattern, *proxy it* through a secure backend that:
  - Accepts a short-lived, non-sensitive identifier.
  - Resolves it to the real secret server-side.
  - Never exposes the raw token in client-visible URLs.

### 10.2. Pitfall: Unclear error messages to the model

If your tools throw generic errors like “401 unauthorized” without context, the model may:

- Repeatedly retry a failing call.
- Fail to instruct the user to complete the auth flow.

Instead:

- Raise **structured, explanatory errors** when auth is missing or expired:
  - e.g., `"AUTH_REQUIRED: Please use 'todo_auth_link' to connect your account."`
- Document this behavior so clients and model prompts encourage the right behavior.

### 10.3. Pitfall: Tightly coupling auth flows to a single client

If your authorization design assumes a specific client UI, it may break as MCP spreads across different clients (desktop, CLI, web).

To avoid this:

- Treat link resources as **client-agnostic**: any client capable of rendering links and opening a browser should work.
- Avoid assumptions about specific JavaScript environments, DOM APIs, or UI components.
- Keep all critical security checks on the **server-side**, not in client-only logic.

### 10.4. Pitfall: Ignoring multi-tenant or multi-user contexts

In organizations:

- A single MCP server might serve many users across teams or tenants.
- Tokens and permissions must be isolated.

Best practices:

- Include `userId`, `tenantId`, or similar context in all auth flows and storage.
- Design your `state` handling in OAuth to protect against cross-tenant confusion.
- When possible, enforce **RBAC** or similar controls at the server level.

---

## 11. Advanced patterns and extensions

Once you have basic auth via link resources working, you can explore more advanced scenarios.

### 11.1. Admin-mediated authorization

For sensitive resources (production databases, billing systems):

- Normal users might not be allowed to directly authorize access.
- Instead, link resources can point to **admin approval flows**.

Example pattern:

1. User tries to run a tool `run_prod_query`.
2. Server detects the user lacks admin-approved authorization.
3. Model tells the user:
   - “You don’t have approval to run queries on production. You can request it via this link.”
4. Link resource opens:
   - An internal approval portal where admins review and grant scoped access.

### 11.2. Device-flow or out-of-band authorization

In constrained environments (e.g., CLI-based MCP clients):

- You may not have a traditional browser or redirect URI.
- OAuth device flows can be used instead.

Link resources can still help:

- Expose a link resource that points to instructions:
  - “Visit https://example.com/device and enter code XYZ.”
- Or to a page that explains:
  - How to perform the device authorization step.

### 11.3. Granular per-resource or per-tool consent

Instead of one monolithic “connect everything” flow:

- Provide **separate link resources** for different capabilities:
  - `github_repo_read_link`
  - `github_issues_manage_link`
- Users can authorize only the subset they feel comfortable with.
- Your MCP server enforces which tools require which grants.

This is especially valuable in regulated environments.

---

## 12. Practical checklist for implementers

If you’re building or extending an MCP server with authorization via link resources, use this checklist:

1. **Identify external services**  
   - List the APIs/tools you’ll wrap.
   - Determine the auth mechanisms (OAuth2, API keys, SSO, etc.).

2. **Define link resources**  
   - For each service (or group of capabilities), define one or more link resources:
     - Clear name
     - Human-readable description
     - URL or URL template for the authorization/connection page.

3. **Implement token storage & lookup**  
   - Choose a secure store (DB, KMS-managed secrets, etc.).
   - Map tokens to user and/or tenant.
   - Implement helper functions like `requireAuth(userId)`.

4. **Wire tools to auth state**  
   - Before calling external APIs, check for valid tokens.
   - On missing or expired tokens, surface descriptive errors that:
     - Indicate which link resource to use.
     - Do not reveal secrets.

5. **Handle callback flows**  
   - For OAuth and similar flows, build callback endpoints.
   - Validate `state` to tie flows to correct users.
   - On success, store tokens and show a clear success page.

6. **Coordinate with clients**  
   - Document your link resources and auth-related error messages.
   - Help client maintainers:
     - Render link resources as clickable UI.
     - Provide a “Connections” page if relevant.
     - Poll or query connection status after auth.

7. **Test realistic scenarios**  
   - User with no connections.
   - User with expired tokens.
   - User revoking access externally.
   - Multi-user concurrency.

8. **Review security**  
   - No tokens or secrets in logs, URLs, or model context.
   - All data at rest encrypted when needed.
   - Proper access control and scoping.

---

## Conclusion

MCP is a powerful way to connect AI to the real world—but that power only remains safe and trustworthy if authorization is handled carefully. **Link resources** are a crucial building block in that design:

- They give models a structured way to **ask for authorization** without seeing secrets.
- They let MCP clients present clear, user-friendly **“Connect X”** experiences.
- They support a wide variety of flows, from OAuth to internal approval portals.

By treating link resources as the **human-facing entry point** to your auth flows, and keeping tokens and permissions managed server-side, you can:

- Build rich, multi-service MCP integrations.
- Respect user privacy and organizational boundaries.
- Maintain a clear, auditable security posture.

As MCP ecosystems grow—spanning IDEs, desktops, web apps, and more—this architecture will become increasingly important. Designing your authorization strategy around link resources today will make your integrations more portable, secure, and user-friendly for the long run.