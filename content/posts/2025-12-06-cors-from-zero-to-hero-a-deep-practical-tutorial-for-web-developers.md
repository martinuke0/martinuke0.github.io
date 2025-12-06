---
title: "CORS From Zero to Hero: A Deep, Practical Tutorial for Web Developers"
date: "2025-12-06T11:53:22.01"
draft: false
tags: ["CORS", Web Security", "HTTP", "JavaScript", "Backend", "DevOps"]
---

## Introduction

Cross-Origin Resource Sharing (CORS) is one of the most misunderstood parts of modern web development. It sits at the intersection of browsers, HTTP, and security, and when it goes wrong you often see opaque errors like “CORS policy: No ‘Access-Control-Allow-Origin’ header…”. This guide takes you from zero to hero: you’ll learn the mental model behind CORS, how the browser enforces it, how to configure servers correctly across popular stacks, how to optimize performance, and how to avoid common security pitfalls.

> Key point: CORS is a browser-enforced relaxation of the Same-Origin Policy. It’s not an authentication mechanism and does not apply to server-to-server requests.

If you just need the TL;DR: allow only the origins you trust, respond correctly to preflight requests, set `Vary: Origin`, never use `Access-Control-Allow-Origin: *` with credentials, and test with real browsers (not Postman).

## Table of Contents

- [Introduction](#introduction)
- [CORS Mental Model](#cors-mental-model)
  - [Origin, Site, and the Same-Origin Policy](#origin-site-and-the-same-origin-policy)
  - [When CORS Applies (and When It Doesn’t)](#when-cors-applies-and-when-it-doesnt)
- [Request Types: Simple, Preflight, and Actual](#request-types-simple-preflight-and-actual)
  - [Simple Requests](#simple-requests)
  - [Preflighted Requests](#preflighted-requests)
  - [The Actual Request](#the-actual-request)
- [CORS Headers Explained](#cors-headers-explained)
  - [Browser-Sent Headers](#browser-sent-headers)
  - [Server-Sent Headers](#server-sent-headers)
  - [Private Network Access (PNA)](#private-network-access-pna)
- [Client-Side Usage](#client-side-usage)
  - [Fetch API Examples](#fetch-api-examples)
  - [Axios Examples](#axios-examples)
  - [Images, Fonts, and Canvas](#images-fonts-and-canvas)
- [Server Configuration Patterns](#server-configuration-patterns)
  - [General Strategy and Checklist](#general-strategy-and-checklist)
  - [Node.js (Express) — with and without middleware](#nodejs-express--with-and-without-middleware)
  - [Python (Flask, FastAPI)](#python-flask-fastapi)
  - [Nginx Reverse Proxy](#nginx-reverse-proxy)
  - [Java (Spring Boot)](#java-spring-boot)
  - [.NET (ASP.NET Core)](#net-aspnet-core)
  - [S3 and CDNs (CloudFront)](#s3-and-cdns-cloudfront)
- [Optimizing Preflight and Performance](#optimizing-preflight-and-performance)
- [Security Best Practices and Pitfalls](#security-best-practices-and-pitfalls)
- [Debugging and Testing CORS](#debugging-and-testing-cors)
- [Edge Cases and Gotchas](#edge-cases-and-gotchas)
- [Best-Practices Checklist](#best-practices-checklist)
- [Conclusion](#conclusion)
- [Resources](#resources)

## CORS Mental Model

### Origin, Site, and the Same-Origin Policy

- Origin = scheme + host + port. Examples:
  - https://app.example.com:443
  - http://api.example.com:80
- Same-origin means all three match exactly.
- Same-site is broader (based on registrable domain, e.g., example.com). This matters for cookies (SameSite) but not directly for CORS decisions.

Browsers enforce the Same-Origin Policy (SOP) to stop a page from reading responses from a different origin. CORS provides a controlled way to relax that restriction when the server opts in.

### When CORS Applies (and When It Doesn’t)

Applies:
- Browser-initiated cross-origin requests from web pages (XHR/fetch, fonts, images with canvas access, video/audio, EventSource, etc.)
- Service workers fetching cross-origin resources.

Does not apply:
- Server-to-server requests (curl, Node fetch on the server, backend APIs calling other APIs)
- Native apps
- WebSockets (they have an Origin header check, but not “CORS”)
- `<img>`/`<script>` tags can request cross-origin without CORS, but reading their responses is restricted (e.g., canvas tainting for images).

## Request Types: Simple, Preflight, and Actual

### Simple Requests

A request is “simple” (no preflight) if:
- Method is GET, HEAD, or POST
- Request headers are limited to the CORS-safelisted ones
  - Accept, Accept-Language, Content-Language
  - Content-Type restricted to: application/x-www-form-urlencoded, multipart/form-data, or text/plain
- No event listeners for upload progress (XHR)
- No `ReadableStream` request body

Examples that are NOT simple:
- `Content-Type: application/json`
- Custom headers (e.g., X-Requested-With)
- Methods like PUT, PATCH, DELETE

### Preflighted Requests

For non-simple requests, the browser first sends an OPTIONS “preflight” with:
- Origin
- Access-Control-Request-Method
- Access-Control-Request-Headers (if any)

The server must respond approving the method and headers before the browser will send the actual request.

### The Actual Request

If approved, the browser sends the actual request. The server must include the appropriate CORS response headers again (e.g., `Access-Control-Allow-Origin`) on the actual response or the browser will block the response from being read.

> Important: The presence of CORS headers on error responses (4xx/5xx) still matters. Without them, the browser may hide the response body from the page.

## CORS Headers Explained

### Browser-Sent Headers

- Origin: The requesting page’s origin. Example: `Origin: https://app.example.com`
- Access-Control-Request-Method: Sent in preflight to declare the method of the upcoming request.
- Access-Control-Request-Headers: Sent in preflight to declare non-safelisted headers that will be sent.
- Sec-Fetch-* headers: Metadata about the request’s context (not directly related to CORS allow lists).

### Server-Sent Headers

- Access-Control-Allow-Origin: Which origin is allowed. Values:
  - `*` (wildcard) allows any origin for non-credentialed requests
  - Or a specific origin, e.g., `https://app.example.com`
- Access-Control-Allow-Credentials: `true` if credentials are allowed (cookies, HTTP auth). Cannot be used with `*` in `Access-Control-Allow-Origin`.
- Access-Control-Allow-Methods: Methods allowed in the actual request (preflight response).
- Access-Control-Allow-Headers: Request headers allowed in the actual request (preflight response).
- Access-Control-Max-Age: How long the preflight result can be cached by the browser (seconds). Browsers impose caps.
- Access-Control-Expose-Headers: Response headers the browser is allowed to expose to the page, beyond the safelisted ones.
- Vary: When `Access-Control-Allow-Origin` is dynamic, include `Vary: Origin`. For preflights, it’s often prudent to include `Vary: Origin, Access-Control-Request-Method, Access-Control-Request-Headers`.

CORS-safelisted response headers (always readable): Cache-Control, Content-Language, Content-Type, Expires, Last-Modified, Pragma.

> Note: `Authorization` request header does NOT require `Access-Control-Allow-Credentials: true`. Credentials in CORS refer to cookies, HTTP authentication, or client certificates. `Authorization` itself can be allowed via preflight without enabling cookies.

### Private Network Access (PNA)

When a public website makes a CORS request to a resource on a private network (e.g., http://192.168.1.10), Chromium-based browsers require an additional preflight:

- Browser preflight includes: `Access-Control-Request-Private-Network: true`
- Server must respond with: `Access-Control-Allow-Private-Network: true`

This protects devices on local networks from arbitrary cross-site access.

## Client-Side Usage

### Fetch API Examples

Simple GET (no preflight if response doesn’t require credentials):
```js
// mode: 'cors' is the default for cross-origin fetch in browsers
const res = await fetch('https://api.example.com/public');
const data = await res.json();
```

JSON POST (triggers preflight because of Content-Type):
```js
const res = await fetch('https://api.example.com/items', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ name: 'Widget' })
});
if (!res.ok) throw new Error('Request failed');
```

Reading custom response headers (requires expose on server):
```js
const res = await fetch('https://api.example.com/items/123');
const requestId = res.headers.get('x-request-id'); // null unless server exposes it
```

With cookies (credentials):
```js
const res = await fetch('https://api.example.com/user', {
  credentials: 'include' // requires server to send ACAO matching origin + ACAC: true
});
```

Opaque response with no-cors (you can’t read it):
```js
const res = await fetch('https://cdn.example.com/asset', { mode: 'no-cors' });
// res.type === 'opaque'; res.ok is false-ish; you cannot read body or most headers
```

### Axios Examples

```js
import axios from 'axios';

// Basic GET
const { data } = await axios.get('https://api.example.com/public');

// JSON POST (preflight likely)
await axios.post('https://api.example.com/items', { name: 'Widget' });

// With credentials (cookies)
const client = axios.create({ withCredentials: true });
const me = await client.get('https://api.example.com/me');
```

### Images, Fonts, and Canvas

- To draw an image on a canvas and read pixels, the image must be loaded with CORS and the server must allow it.
- For fonts, many browsers require CORS headers when loading cross-origin fonts.

```html
<!-- Image usable in canvas if server sets Access-Control-Allow-Origin -->
<img id="pic" crossorigin="anonymous" src="https://img.example.com/photo.jpg" />

<canvas id="c"></canvas>
<script>
  const img = document.getElementById('pic');
  img.onload = () => {
    const c = document.getElementById('c');
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    // canvas is not tainted if CORS succeeded
    const pixel = ctx.getImageData(0, 0, 1, 1);
    console.log(pixel);
  };
</script>
```

## Server Configuration Patterns

### General Strategy and Checklist

1. Maintain an allowlist of trusted origins.
2. For preflight (OPTIONS):
   - Validate Origin, Access-Control-Request-Method, and Access-Control-Request-Headers.
   - Respond with 204/200 and include:
     - Access-Control-Allow-Origin: matched origin
     - Access-Control-Allow-Methods: allowed methods
     - Access-Control-Allow-Headers: allowed headers (or `*` judiciously)
     - Access-Control-Allow-Credentials: true (only if you accept credentials)
     - Access-Control-Max-Age: N (optional)
     - Vary: Origin, Access-Control-Request-Method, Access-Control-Request-Headers
3. For actual responses:
   - Include Access-Control-Allow-Origin (and ACAC if applicable)
   - Include Access-Control-Expose-Headers for any custom headers you want readable
   - Include Vary: Origin when ACAO is dynamic
4. Never use `*` in ACAO when sending credentials.
5. Don’t reflect arbitrary origins blindly without validation.
6. Test with browser DevTools; verify response headers on both preflight and actual responses.

### Node.js (Express) — with and without middleware

Using the popular `cors` middleware:
```js
import express from 'express';
import cors from 'cors';

const app = express();

const allowlist = ['https://app.example.com', 'https://admin.example.com'];
const corsOptions = {
  origin(origin, cb) {
    // Allow same-origin (no Origin header) like curl or server-to-server
    if (!origin) return cb(null, true);
    if (allowlist.includes(origin)) return cb(null, true);
    return cb(new Error('Not allowed by CORS'));
  },
  methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization', 'X-Requested-With'],
  exposedHeaders: ['X-Request-Id', 'ETag'],
  credentials: true,
  maxAge: 600, // seconds
};

app.use(cors(corsOptions));
// Optionally handle preflight explicitly for legacy clients
app.options('*', cors(corsOptions));

app.get('/me', (req, res) => {
  res.set('X-Request-Id', 'abc123'); // exposed by CORS
  res.json({ id: 42 });
});

app.listen(3000);
```

Manual implementation (fine-grained control):
```js
import express from 'express';
const app = express();

const allowlist = new Set(['https://app.example.com', 'https://admin.example.com']);

app.use((req, res, next) => {
  const origin = req.headers.origin;
  if (origin && allowlist.has(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Access-Control-Allow-Credentials', 'true');
    res.setHeader('Vary', 'Origin');
  }
  next();
});

app.options('*', (req, res) => {
  const origin = req.headers.origin;
  const reqMethod = req.headers['access-control-request-method'];
  const reqHeaders = req.headers['access-control-request-headers'];

  if (origin && allowlist.has(origin) && reqMethod) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Access-Control-Allow-Credentials', 'true');
    res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PUT,PATCH,DELETE,OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', reqHeaders || 'Content-Type,Authorization');
    res.setHeader('Access-Control-Max-Age', '600');
    res.setHeader('Vary', 'Origin, Access-Control-Request-Method, Access-Control-Request-Headers');
    return res.sendStatus(204);
  }
  return res.sendStatus(403);
});

// routes...
```

### Python (Flask, FastAPI)

Flask with `flask-cors`:
```python
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app,
     resources={r"/api/*": {"origins": ["https://app.example.com", "https://admin.example.com"]}},
     supports_credentials=True,
     expose_headers=["X-Request-Id", "ETag"],
     max_age=600)

@app.route('/api/me')
def me():
    return jsonify({"id": 42})
```

FastAPI with `CORSMiddleware`:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
origins = ["https://app.example.com", "https://admin.example.com"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "ETag"],
    max_age=600
)

@app.get("/me")
def read_me():
    return {"id": 42}
```

### Nginx Reverse Proxy

```nginx
# Map approved origins to a variable
map $http_origin $cors_origin {
    "~^https://(app|admin)\.example\.com$"  $http_origin;
    default                                 "";
}

server {
    listen 443 ssl;
    server_name api.example.com;

    # Preflight handler
    if ($request_method = OPTIONS) {
        add_header 'Access-Control-Allow-Origin'      $cors_origin always;
        add_header 'Access-Control-Allow-Credentials' 'true' always;
        add_header 'Access-Control-Allow-Methods'     'GET,POST,PUT,PATCH,DELETE,OPTIONS' always;
        add_header 'Access-Control-Allow-Headers'     $http_access_control_request_headers always;
        add_header 'Access-Control-Max-Age'           '600' always;
        add_header 'Vary' 'Origin, Access-Control-Request-Method, Access-Control-Request-Headers' always;
        return 204;
    }

    location / {
        proxy_pass http://backend;
        # Actual responses
        add_header 'Access-Control-Allow-Origin'      $cors_origin always;
        add_header 'Access-Control-Allow-Credentials' 'true' always;
        add_header 'Vary' 'Origin' always;
    }
}
```

### Java (Spring Boot)

Java config:
```java
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class CorsConfig {
  @Bean
  public WebMvcConfigurer corsConfigurer() {
    return new WebMvcConfigurer() {
      @Override
      public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")
          .allowedOrigins("https://app.example.com", "https://admin.example.com")
          .allowedMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
          .allowedHeaders("*")
          .exposedHeaders("X-Request-Id", "ETag")
          .allowCredentials(true)
          .maxAge(600);
      }
    };
  }
}
```

application.yml alternative:
```yaml
spring:
  web:
    cors:
      mappings:
        - path: /**
          allowed-origins: "https://app.example.com,https://admin.example.com"
          allowed-methods: GET,POST,PUT,PATCH,DELETE,OPTIONS
          allowed-headers: "*"
          exposed-headers: X-Request-Id,ETag
          allow-credentials: true
          max-age: 600
```

### .NET (ASP.NET Core)

```csharp
var builder = WebApplication.CreateBuilder(args);

builder.Services.AddCors(options =>
{
    options.AddPolicy("Default", policy =>
    {
        policy.WithOrigins("https://app.example.com", "https://admin.example.com")
              .AllowAnyMethod()
              .AllowAnyHeader()
              .WithExposedHeaders("X-Request-Id", "ETag")
              .AllowCredentials();
    });
});

var app = builder.Build();

app.UseCors("Default");

app.MapGet("/me", () => Results.Json(new { id = 42 }));

app.Run();
```

### S3 and CDNs (CloudFront)

S3 bucket CORS configuration:
```json
[
  {
    "AllowedOrigins": ["https://app.example.com"],
    "AllowedMethods": ["GET", "PUT"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 600
  }
]
```

CloudFront considerations:
- Forward the Origin header to the origin if you return dynamic `Access-Control-Allow-Origin`.
- Cache based on Origin (configure Origin Request Policy / Cache Policy).
- Add `Vary: Origin` on origin responses.

## Optimizing Preflight and Performance

- Prefer simple requests:
  - Use GET or POST where possible.
  - For POST, use `multipart/form-data` or `application/x-www-form-urlencoded` if appropriate.
  - Avoid unnecessary custom headers.
- Consolidate APIs on the same origin as your app via reverse proxying to avoid CORS entirely.
- Set `Access-Control-Max-Age` to cache preflights (e.g., 600 seconds). Browsers cap this value; expect variance across browsers.
- Batch requests where possible; reduce chattiness.
- Use CDNs close to the client to minimize latency for both preflight and actual requests.
- For GraphQL or JSON-heavy APIs, consider keeping a stable set of request headers to maximize preflight cache hits.

> Note: Preflight results are per-origin, per-method, and per-header-set. Changing headers frequently reduces cache effectiveness.

## Security Best Practices and Pitfalls

- Do not use CORS as an auth mechanism. It only controls browser access.
- Never send `Access-Control-Allow-Origin: *` together with `Access-Control-Allow-Credentials: true`. Browsers will reject.
- Prefer explicit allowlists. If you must support patterns, validate carefully (e.g., `https://*.example.com`) and avoid regexes that can be bypassed (`example.com.evil.tld`).
- Set cookies with `SameSite` appropriately:
  - Cross-site requests that require cookies need `SameSite=None; Secure`.
  - To mitigate CSRF, prefer `SameSite=Lax/Strict` where possible, combine with CSRF tokens on state-changing routes.
- Include `Vary: Origin` when ACAO is dynamic to prevent cache poisoning or data leakage via shared caches.
- Don’t blindly reflect `Access-Control-Request-Headers` and `Access-Control-Request-Method` without policy—limit to what your API supports.
- WebSockets are not governed by CORS. Validate the `Origin` header on upgrade.
- For PNA (private network access), only opt-in (`Access-Control-Allow-Private-Network: true`) if you intentionally serve private-network clients.

## Debugging and Testing CORS

- Use DevTools Network panel:
  - Look for the OPTIONS preflight.
  - Inspect request and response headers for both preflight and actual