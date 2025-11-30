---
title: "The Complete Guide to Building a Cloudflare Workers OpenAI Proxy: From Beginner to Hero"
date: 2025-11-28T16:15:00+02:00
draft: false
tags: ["cloudflare-workers", "openai", "api", "javascript", "web-development", "proxy"]
---

Using OpenAI APIs in frontend code is risky — exposing your API key is a security hazard.  
The solution is a **Cloudflare Worker** that acts as a secure proxy. Your frontend calls the worker; the worker calls OpenAI with your key. The key stays secret.

This guide is **beginner-friendly**, ELI5 style, and gradually moves to advanced techniques like streaming, caching, and rate-limiting.

---

## Beginner: Why You Need a Proxy

Imagine you have a magic key that unlocks a powerful AI genie.  
If you give that key to everyone, anyone can spend your genie’s wishes. That’s what happens if you put your API key in frontend code.  

Solution: Keep the key in a secret backend (Cloudflare Worker). Your app only talks to the Worker, not directly to OpenAI.

---

## Setting Up a Cloudflare Worker

### Step 1: Sign Up and Install Wrangler

1. **Sign up for Cloudflare**: [https://workers.cloudflare.com/](https://workers.cloudflare.com/)
2. **Install Wrangler (CLI for Workers)**:

```bash
npm install -g wrangler
```

3. **Login with Wrangler**:

```bash
wrangler login
```

4. **Create a new Worker project**:

```bash
wrangler generate openai-proxy
cd openai-proxy
```

---

## Beginner: Basic Worker Proxy

### Creating Your First Proxy

Create a file `index.js`:

```javascript
export default {
  async fetch(request, env) {
    const url = "https://api.openai.com/v1/chat/completions";
    const body = await request.json();

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${env.OPENAI_API_KEY}`
      },
      body: JSON.stringify(body)
    });

    const data = await response.json();
    return new Response(JSON.stringify(data), {
      headers: { "Content-Type": "application/json" }
    });
  }
};
```

**Notice:** `OPENAI_API_KEY` is not hardcoded. We access it through `env.OPENAI_API_KEY`. We'll set it as a secret next.

---

## Adding Secrets

Set your OpenAI key securely:

```bash
wrangler secret put OPENAI_API_KEY
```

Type your API key when prompted. Now, your Worker can access it securely as `env.OPENAI_API_KEY`.

---

## Deploying Your Worker

Deploy your Worker:

```bash
wrangler deploy
```

You will get a URL like:

```
https://openai-proxy.your-subdomain.workers.dev
```

Your frontend can now call this URL instead of OpenAI directly.

---

## Intermediate: Using Chat Completions

### Making Requests from Your Frontend

Example request from your frontend:

```javascript
const response = await fetch("https://openai-proxy.your-subdomain.workers.dev", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "gpt-4",
    messages: [{ role: "user", content: "Hello AI!" }]
  })
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

### Adding CORS Support

To allow your frontend to call the Worker, add CORS headers:

```javascript
export default {
  async fetch(request, env) {
    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    const url = "https://api.openai.com/v1/chat/completions";
    const body = await request.json();

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${env.OPENAI_API_KEY}`
      },
      body: JSON.stringify(body)
    });

    const data = await response.json();

    return new Response(JSON.stringify(data), {
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      }
    });
  }
};
```

---

## Advanced: Streaming Responses

For real-time streaming (like ChatGPT):

```javascript
export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    const body = await request.json();

    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${env.OPENAI_API_KEY}`
      },
      body: JSON.stringify({ ...body, stream: true })
    });

    return new Response(response.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Access-Control-Allow-Origin": "*",
      }
    });
  }
};
```

### Frontend: Consuming Streaming Responses

```javascript
const response = await fetch("https://openai-proxy.your-subdomain.workers.dev", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "gpt-4",
    messages: [{ role: "user", content: "Tell me a story" }],
    stream: true
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const chunk = decoder.decode(value);
  const lines = chunk.split('\n').filter(line => line.trim() !== '');

  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data = line.slice(6);
      if (data === '[DONE]') continue;

      try {
        const parsed = JSON.parse(data);
        const content = parsed.choices[0]?.delta?.content || '';
        if (content) {
          console.log(content); // Stream the text as it arrives
        }
      } catch (e) {
        console.error('Parse error:', e);
      }
    }
  }
}
```

---

## Pro: Rate Limiting & Security

### Rate Limiting with Cloudflare KV

Protect your API key from abuse:

```javascript
export default {
  async fetch(request, env) {
    const ip = request.headers.get('CF-Connecting-IP');
    const key = `rate_limit:${ip}`;

    // Check rate limit
    const count = await env.KV.get(key);
    if (count && parseInt(count) > 100) { // 100 requests per hour
      return new Response('Rate limit exceeded', { status: 429 });
    }

    // Increment counter
    await env.KV.put(key, (parseInt(count || 0) + 1).toString(), {
      expirationTtl: 3600 // 1 hour
    });

    // Continue with normal flow
    const body = await request.json();
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${env.OPENAI_API_KEY}`
      },
      body: JSON.stringify(body)
    });

    const data = await response.json();
    return new Response(JSON.stringify(data), {
      headers: { "Content-Type": "application/json" }
    });
  }
};
```

**Setup KV Namespace:**

```bash
wrangler kv:namespace create KV
```

Add to `wrangler.toml`:

```toml
kv_namespaces = [
  { binding = "KV", id = "your-namespace-id" }
]
```

### Caching Responses

Cache repeated prompts to save API calls:

```javascript
export default {
  async fetch(request, env) {
    const body = await request.json();
    const cacheKey = `cache:${JSON.stringify(body)}`;

    // Check cache
    const cached = await env.KV.get(cacheKey);
    if (cached) {
      return new Response(cached, {
        headers: { "Content-Type": "application/json" }
      });
    }

    // Make API call
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${env.OPENAI_API_KEY}`
      },
      body: JSON.stringify(body)
    });

    const data = await response.json();
    const responseText = JSON.stringify(data);

    // Cache for 1 hour
    await env.KV.put(cacheKey, responseText, {
      expirationTtl: 3600
    });

    return new Response(responseText, {
      headers: { "Content-Type": "application/json" }
    });
  }
};
```

### Request Validation

Validate incoming requests to prevent misuse:

```javascript
function validateRequest(body) {
  if (!body.model || !body.messages) {
    return { valid: false, error: 'Missing required fields' };
  }

  // Limit message length
  const totalLength = body.messages.reduce((sum, msg) => sum + msg.content.length, 0);
  if (totalLength > 10000) {
    return { valid: false, error: 'Message too long' };
  }

  // Only allow certain models
  const allowedModels = ['gpt-4', 'gpt-3.5-turbo'];
  if (!allowedModels.includes(body.model)) {
    return { valid: false, error: 'Model not allowed' };
  }

  return { valid: true };
}

export default {
  async fetch(request, env) {
    const body = await request.json();

    // Validate
    const validation = validateRequest(body);
    if (!validation.valid) {
      return new Response(JSON.stringify({ error: validation.error }), {
        status: 400,
        headers: { "Content-Type": "application/json" }
      });
    }

    // Continue with API call...
  }
};
```

---

## Complete Production-Ready Example

Here's a full-featured Worker with all the bells and whistles:

```javascript
export default {
  async fetch(request, env, ctx) {
    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
      });
    }

    // Only allow POST
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    try {
      // Rate limiting
      const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
      const rateLimitKey = `rate:${ip}`;
      const requestCount = await env.KV.get(rateLimitKey);

      if (requestCount && parseInt(requestCount) > 50) {
        return new Response(JSON.stringify({ error: 'Rate limit exceeded' }), {
          status: 429,
          headers: { "Content-Type": "application/json" }
        });
      }

      await env.KV.put(rateLimitKey, (parseInt(requestCount || 0) + 1).toString(), {
        expirationTtl: 3600
      });

      // Parse and validate request
      const body = await request.json();

      if (!body.model || !body.messages) {
        return new Response(JSON.stringify({ error: 'Invalid request' }), {
          status: 400,
          headers: { "Content-Type": "application/json" }
        });
      }

      // Check cache (only for non-streaming requests)
      if (!body.stream) {
        const cacheKey = `cache:${JSON.stringify(body)}`;
        const cached = await env.KV.get(cacheKey);

        if (cached) {
          console.log('Cache hit');
          return new Response(cached, {
            headers: {
              "Content-Type": "application/json",
              "Access-Control-Allow-Origin": "*",
              "X-Cache": "HIT"
            }
          });
        }
      }

      // Make OpenAI request
      const openaiResponse = await fetch("https://api.openai.com/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${env.OPENAI_API_KEY}`
        },
        body: JSON.stringify(body)
      });

      // Handle streaming
      if (body.stream) {
        return new Response(openaiResponse.body, {
          headers: {
            "Content-Type": "text/event-stream",
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
          }
        });
      }

      // Handle regular response
      const data = await openaiResponse.json();
      const responseText = JSON.stringify(data);

      // Cache successful responses
      if (openaiResponse.ok) {
        const cacheKey = `cache:${JSON.stringify(body)}`;
        ctx.waitUntil(
          env.KV.put(cacheKey, responseText, { expirationTtl: 3600 })
        );
      }

      return new Response(responseText, {
        status: openaiResponse.status,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*",
          "X-Cache": "MISS"
        }
      });

    } catch (error) {
      console.error('Error:', error);
      return new Response(JSON.stringify({ error: 'Internal server error' }), {
        status: 500,
        headers: { "Content-Type": "application/json" }
      });
    }
  }
};
```

---

## Resources

### Official Documentation

- **Cloudflare Workers**: [developers.cloudflare.com/workers](https://developers.cloudflare.com/workers/)
- **OpenAI API**: [platform.openai.com/docs/api-reference](https://platform.openai.com/docs/api-reference)
- **Wrangler CLI**: [developers.cloudflare.com/workers/wrangler](https://developers.cloudflare.com/workers/wrangler/)

### Learning Resources

- **Cloudflare Workers Examples**: [github.com/cloudflare/workers-sdk](https://github.com/cloudflare/workers-sdk)
- **OpenAI Streaming Guide**: [platform.openai.com/docs/api-reference/streaming](https://platform.openai.com/docs/api-reference/streaming)
- **Cloudflare KV Storage**: [developers.cloudflare.com/kv](https://developers.cloudflare.com/kv/)

### Tools

- **Wrangler CLI**: The official Cloudflare Workers CLI tool
- **Miniflare**: Local Cloudflare Workers simulator for testing
- **OpenAI Node SDK**: Official OpenAI library for Node.js

---

## Conclusion

You now have a production-ready OpenAI proxy with:
- ✅ Secure API key management
- ✅ CORS support for frontend apps
- ✅ Streaming responses
- ✅ Rate limiting
- ✅ Response caching
- ✅ Request validation
- ✅ Error handling

Deploy it, test it, and build amazing AI-powered applications!

