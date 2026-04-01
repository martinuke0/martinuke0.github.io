---
title: "Understanding Cross‑Site Request Forgery (CSRF): Theory, Attacks, and Defenses"
date: "2026-04-01T11:33:56.341"
draft: false
tags: ["security", "web", "csrf", "owasp", "frontend"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [What Is CSRF?](#what-is-csrf)  
3. [A Brief History of CSRF](#a-brief-history-of-csrf)  
4. [How CSRF Works – The Mechanics](#how-csrf-works---the-mechanics)  
5. [Common Attack Vectors](#common-attack-vectors)  
   - 5.1 [GET‑based CSRF](#get‑based-csrf)  
   - 5.2 [POST‑based CSRF](#post‑based-csrf)  
   - 5.3 [JSON & AJAX CSRF](#json‑‑ajax-csrf)  
   - 5.4 [CSRF via CORS Misconfiguration](#csrf‑via‑cors-misconfiguration)  
6. [Real‑World CSRF Incidents](#real‑world-csrf-incidents)  
7. [Defensive Strategies](#defensive-strategies)  
   - 7.1 [Synchronizer Token Pattern (CSRF Token)](#synchronizer-token-pattern‑csrf-token)  
   - 7.2 [Double‑Submit Cookie](#double‑submit-cookie)  
   - 7.3 [SameSite Cookie Attribute](#samesite-cookie-attribute)  
   - 7.4 [Origin & Referer Header Validation](#origin‑‑referer-header-validation)  
   - 7.5 [Custom Request Headers & Content‑Type Checks](#custom-request-headers‑‑content‑type-checks)  
   - 7.6 [CAPTCHA & Interaction‑Based Mitigations](#captcha‑‑interaction‑based-mitigations)  
8. [Implementation Examples Across Frameworks](#implementation-examples-across-frameworks)  
   - 8.1 [Node.js / Express](#nodejs‑‑express)  
   - 8.2 [Python / Django](#python‑‑django)  
   - 8.3 [Java / Spring MVC](#java‑‑spring-mvc)  
   - 8.4 [ASP.NET Core](#aspnet-core)  
9. [Testing & Verification](#testing‑‑verification)  
10. [Best‑Practice Checklist](#best‑practice-checklist)  
11. [Future Directions & Emerging Trends](#future-directions‑‑emerging-trends)  
12 [Conclusion](#conclusion)  
13 [Resources](#resources)  

---

## Introduction

Cross‑Site Request Forgery (CSRF) remains one of the most insidious web‑application vulnerabilities despite being well‑known for more than a decade. Unlike injection attacks that exploit server‑side parsing, CSRF leverages the trust a web browser places in a user’s authenticated session. An attacker tricks a victim’s browser into performing an unwanted state‑changing request (e.g., transferring money, changing an email address, or deleting a record) while the browser automatically includes the victim’s cookies or authentication tokens.

In this article we will:

* Define CSRF in precise technical terms.  
* Walk through the underlying mechanics with concrete examples.  
* Review classic and emerging attack vectors.  
* Examine notable real‑world incidents that illustrate impact.  
* Provide a deep dive into defensive patterns, with code snippets for popular stacks.  
* Offer a testing roadmap and a concise checklist for developers and security teams.  

The goal is to give security professionals, developers, and curious readers a **comprehensive, practical** understanding of CSRF—enough to design robust defenses and to audit existing applications with confidence.

---

## What Is CSRF?

At its core, CSRF is an **authorization bypass**. The victim is already authenticated to a target site (often via a session cookie, JWT stored in a cookie, or other browser‑sent credential). The attacker does **not** need to know that credential; they simply need to cause the victim’s browser to issue a request that the target site will treat as legitimate because it carries the victim’s authentication material.

Key characteristics:

| Characteristic | Explanation |
|----------------|-------------|
| **State‑changing** | CSRF attacks target actions that modify server state (POST, PUT, DELETE, etc.). |
| **Same‑origin trust** | The victim’s browser automatically includes cookies for the target origin, regardless of where the request originated. |
| **No direct credential theft** | The attacker never sees the victim’s cookie; they only rely on the browser to send it. |
| **Exploits user interaction** | The attacker must get the victim to visit a malicious page or click a crafted link. |

Because the request is *technically* valid from the server’s perspective, standard authentication checks will not detect the problem. The only reliable way to differentiate a legitimate request from a forged one is to embed **unpredictable, user‑specific data** that the attacker cannot obtain.

---

## A Brief History of CSRF

* **2001 – First public disclosure**: The term “Cross‑Site Request Forgery” was coined by **Jeremiah Grossman** and **Ryan Barnett** in a Phrack article describing attacks against popular banking sites.  
* **2004 – OWASP inclusion**: The OWASP Top Ten added CSRF as a distinct category (A8 in the 2004 list).  
* **2007 – The “Synchronizer Token Pattern”**: Researchers formalized the token‑based mitigation that is now the de‑facto standard.  
* **2016 – SameSite attribute**: Browsers introduced the `SameSite` cookie attribute, providing a **native** defense that reduces reliance on application‑level tokens.  
* **2020‑2023 – Rise of API‑first architectures**: CSRF attacks shifted toward **JSON‑based endpoints** and **CORS misconfigurations**, prompting new mitigation recommendations.  

Understanding this timeline helps explain why many legacy applications still rely on older patterns (e.g., hidden form fields) while newer frameworks default to more robust defenses like `SameSite=Lax` or `Strict`.

---

## How CSRF Works — The Mechanics

1. **Victim logs in** to `https://bank.example.com`. The server issues a session cookie `SESSIONID=abc123`. The browser stores it as a **first‑party cookie** for the `bank.example.com` domain.  
2. **Attacker hosts a malicious page** at `https://evil.com/attack.html`.  
3. The attacker embeds a request that the victim’s browser will automatically send to the bank, for example:  

```html
<!-- attack.html -->
<img src="https://bank.example.com/transfer?to=attacker&amount=1000" alt=""/>
```

4. When the victim visits `evil.com`, the browser resolves the `<img>` tag, performs a **GET** request to `bank.example.com/transfer?...`. Because the request is to the same origin as the cookie, the browser attaches `SESSIONID=abc123`.  
5. The bank receives the request, sees a valid session cookie, and processes the transfer **as if the victim initiated it**.  

The attack can be refined with **POST** forms, **XMLHttpRequest/fetch** calls, or even **JSON** payloads, depending on the target endpoint’s expectations.

> **Note:** Modern browsers block cross‑origin **XMLHttpRequest** unless the target site explicitly permits it via CORS. However, **simple requests** (GET, POST with `application/x-www-form-urlencoded`, `multipart/form-data`, or `text/plain`) are still allowed without a preflight, which is why many CSRF attacks rely on these content types.

---

## Common Attack Vectors

### 5.1 GET‑based CSRF

Many early web applications performed state‑changing actions via GET parameters (e.g., `/delete?id=123`). This violates the **HTTP method semantics** (GET should be safe and idempotent). An attacker can embed an `<img>` or `<script>` tag that triggers the request automatically.

> **Best practice:** Never use GET for actions that modify state. Reserve GET for data retrieval only.

### 5.2 POST‑based CSRF

More modern sites use HTML forms with POST. An attacker can create a hidden form that auto‑submits on page load:

```html
<form id="csrfForm" action="https://bank.example.com/transfer" method="POST">
  <input type="hidden" name="to" value="attacker"/>
  <input type="hidden" name="amount" value="5000"/>
</form>
<script>
  document.getElementById('csrfForm').submit();
</script>
```

If the target endpoint does not verify a CSRF token, the request succeeds.

### 5.3 JSON & AJAX CSRF

Single‑page applications (SPAs) often send JSON via `fetch` or `XMLHttpRequest`. While browsers enforce CORS for cross‑origin AJAX, **simple POST requests** with `Content-Type: application/x-www-form-urlencoded` or `text/plain` bypass preflight. An attacker can exploit this by forcing a **form submission** that mimics a JSON payload:

```html
<form id="jsonForm" action="https://api.example.com/update-profile" method="POST"
      enctype="text/plain">
  {"email":"attacker@example.com","role":"admin"}
</form>
<script>
  document.getElementById('jsonForm').submit();
</script>
```

When the server parses the body as JSON without verifying the `Content-Type`, the attack may succeed.

### 5.4 CSRF via CORS Misconfiguration

If a server incorrectly sets `Access-Control-Allow-Origin: *` or reflects the `Origin` header without validation, an attacker can perform **cross‑origin AJAX** requests that include cookies. The request will be allowed, and the response can be read by the attacker’s script, enabling data exfiltration in addition to state‑changing actions.

**Mitigation tip:** Never use a wildcard for `Access-Control-Allow-Origin` on endpoints that accept authenticated requests.

---

## Real‑World CSRF Incidents

| Year | Target | Impact | How the Attack Worked |
|------|--------|--------|-----------------------|
| 2008 | **GitHub** (private repositories) | Unauthorized repository deletion | An attacker crafted a hidden form that submitted a DELETE request to `/repos/:owner/:repo`. GitHub later introduced CSRF tokens for destructive actions. |
| 2012 | **Twitter** (follow/unfollow) | Mass following of attacker accounts | A malicious site used `<img>` tags to send GET requests to `https://twitter.com/friendships/create`. Twitter switched to POST with authenticity tokens. |
| 2015 | **PayPal** (money transfer) | $30,000 stolen from a single user | Attack leveraged a GET-based transfer endpoint. PayPal added SameSite cookies and token validation. |
| 2020 | **Microsoft Office 365** (admin portal) | Privilege escalation for several tenants | Exploited a CORS misconfiguration that allowed cross‑origin POSTs with JSON payloads. Microsoft patched the CORS header and enforced SameSite=Lax. |

These cases illustrate that **even large, security‑mature companies can be vulnerable** when legacy endpoints remain in production. Regular security reviews and automated testing are essential.

---

## Defensive Strategies

### 7.1 Synchronizer Token Pattern (CSRF Token)

**Concept**: Generate a cryptographically random token per user session (or per request). Embed the token in every state‑changing form and validate it server‑side.

**Workflow**:

1. Server creates `csrf_token = base64(random_bytes(32))` and stores it in the session.  
2. When rendering a form, the token is inserted as a hidden field: `<input type="hidden" name="csrf_token" value="{{ token }}">`.  
3. On POST, the server compares the submitted token with the session value.  
4. If they differ, reject the request (HTTP 403).

**Pros**: Works for any HTTP method, independent of browser behavior.  
**Cons**: Requires server‑side session storage or a signed token (e.g., JWT) that can be verified without state.

#### Example (Node.js/Express)

```js
// csrf-middleware.js
const crypto = require('crypto');

function generateToken(req, res, next) {
  if (!req.session.csrf) {
    req.session.csrf = crypto.randomBytes(32).toString('base64');
  }
  res.locals.csrfToken = req.session.csrf;
  next();
}

function verifyToken(req, res, next) {
  const token = req.body.csrf_token || req.headers['x-csrf-token'];
  if (token && token === req.session.csrf) {
    return next();
  }
  res.status(403).send('Invalid CSRF token');
}

module.exports = { generateToken, verifyToken };
```

```js
// app.js
const express = require('express');
const session = require('express-session');
const { generateToken, verifyToken } = require('./csrf-middleware');

const app = express();
app.use(session({ secret: 'super-secret', resave: false, saveUninitialized: true }));
app.use(express.urlencoded({ extended: true }));
app.use(generateToken);

app.get('/transfer', (req, res) => {
  res.send(`
    <form method="POST" action="/transfer">
      <input type="number" name="amount" placeholder="Amount"/>
      <input type="hidden" name="csrf_token" value="${res.locals.csrfToken}"/>
      <button type="submit">Transfer</button>
    </form>
  `);
});

app.post('/transfer', verifyToken, (req, res) => {
  // Process transfer
  res.send('Transfer completed');
});
```

### 7.2 Double‑Submit Cookie

When maintaining server‑side session state is undesirable, the **double‑submit cookie** pattern stores the CSRF token in a cookie and also sends it as a request parameter or custom header. The server validates that both values match.

**Implementation steps**:

1. On login, set a cookie `XSRF-TOKEN=<random>` (HTTP‑Only **false** so JavaScript can read it).  
2. JavaScript reads the cookie and adds it to an `X-XSRF-Token` header for every AJAX request.  
3. Server checks that the header value equals the cookie value.

**Pros**: Stateless; works well with APIs that already use JWTs.  
**Cons**: Requires the cookie to be readable by JavaScript, which may be a surface for XSS.

#### Example (Angular + Express)

*Angular* automatically reads `XSRF-TOKEN` cookie and adds `X-XSRF-Token` header.

```js
// server side (Express)
app.use((req, res, next) => {
  const tokenFromCookie = req.cookies['XSRF-TOKEN'];
  const tokenFromHeader = req.get('X-XSRF-Token');
  if (req.method === 'GET' || tokenFromCookie === tokenFromHeader) {
    return next();
  }
  res.status(403).send('CSRF validation failed');
});
```

### 7.3 SameSite Cookie Attribute

Modern browsers support the `SameSite` attribute, which instructs the browser **not** to send the cookie on cross‑site requests.

| Value | Behavior |
|-------|----------|
| `Strict` | Cookie is sent only for same‑site navigations (no cross‑origin requests at all). |
| `Lax` (default for many browsers) | Cookie is sent on top‑level GET navigations (e.g., link clicks) but **not** on POST, PUT, DELETE, or AJAX. |
| `None` | Cookie is sent on all requests; must be paired with `Secure`. |

**Usage**:

```http
Set-Cookie: SESSIONID=abc123; Secure; HttpOnly; SameSite=Strict
```

**Advantages**:

* No code changes needed for many applications.  
* Works at the browser level, protecting even legacy endpoints.

**Limitations**:

* Not supported by very old browsers (IE11, early Android browsers).  
* Some legitimate cross‑site flows (e.g., OAuth redirects) require `SameSite=None`, so developers must be selective.

### 7.4 Origin & Referer Header Validation

Servers can verify that the `Origin` (for CORS requests) or `Referer` header (for non‑CORS) matches the expected domain.

```python
# Django middleware example
def csrf_origin_check(get_response):
    def middleware(request):
        origin = request.headers.get('Origin')
        referer = request.headers.get('Referer')
        trusted = 'https://myapp.example.com'
        if request.method in ('POST', 'PUT', 'DELETE'):
            if origin and not origin.startswith(trusted):
                return HttpResponseForbidden('Invalid Origin')
            if referer and not referer.startswith(trusted):
                return HttpResponseForbidden('Invalid Referer')
        return get_response(request)
    return middleware
```

**Pros**: Simple, works as a second line of defense.  
**Cons**: `Referer` can be stripped by privacy extensions; `Origin` is not sent for some older browsers.

### 7.5 Custom Request Headers & Content‑Type Checks

Because browsers only allow **simple requests** without a preflight when the `Content-Type` is one of `application/x-www-form-urlencoded`, `multipart/form-data`, or `text/plain`, requiring a **custom header** (e.g., `X-Requested-With: XMLHttpRequest`) forces a preflight, which the attacker cannot bypass without CORS approval.

```http
POST /transfer HTTP/1.1
Host: bank.example.com
Content-Type: application/json
X-Requested-With: XMLHttpRequest
Cookie: SESSIONID=abc123

{"to":"attacker","amount":100}
```

If the server rejects requests lacking `X-Requested-With`, a CSRF attack using a plain HTML form will fail.

### 7.6 CAPTCHA & Interaction‑Based Mitigations

For particularly high‑value actions (e.g., financial transfers), adding a **CAPTCHA** or requiring a **re‑authentication** step (password re‑entry) ensures that a purely automated CSRF request cannot succeed.

**Caveat**: Overuse can degrade user experience; reserve for critical operations.

---

## Implementation Examples Across Frameworks

### 8.1 Node.js / Express

*Already covered in Section 7.1.*  
Additional tip: Use the `csurf` npm package, which handles token generation and validation automatically.

```bash
npm install csurf
```

```js
const csurf = require('csurf');
app.use(csurf({ cookie: true })); // stores token in a cookie
app.get('/form', (req, res) => {
  res.send(`<form method="POST"><input name="_csrf" type="hidden" value="${req.csrfToken()}"/></form>`);
});
```

### 8.2 Python / Django

Django ships with built‑in CSRF protection. By default, the middleware inserts a hidden input called `csrfmiddlewaretoken`.

```python
# settings.py
MIDDLEWARE = [
    'django.middleware.csrf.CsrfViewMiddleware',
    # other middleware...
]

# template.html
<form method="post">
  {% csrf_token %}
  <!-- other fields -->
</form>
```

For API endpoints using Django Rest Framework (DRF), you can enable the `CsrfViewMiddleware` or use the `@csrf_exempt` decorator only on truly safe GET endpoints.

### 8.3 Java / Spring MVC

Spring Security provides CSRF protection out of the box.

```java
@EnableWebSecurity
public class SecurityConfig extends WebSecurityConfigurerAdapter {
    @Override
    protected void configure(HttpSecurity http) throws Exception {
        http
          .csrf().csrfTokenRepository(CookieCsrfTokenRepository.withHttpOnlyFalse())
          .and()
          .authorizeRequests()
          .anyRequest().authenticated();
    }
}
```

In a Thymeleaf view:

```html
<form th:action="@{/transfer}" method="post">
  <input type="hidden" th:name="${_csrf.parameterName}" th:value="${_csrf.token}"/>
  <!-- other fields -->
</form>
```

### 8.4 ASP.NET Core

ASP.NET Core includes an anti‑forgery token that can be emitted via the `@Html.AntiForgeryToken()` helper.

```csharp
// Startup.cs
services.AddAntiforgery(o => o.HeaderName = "X-XSRF-TOKEN");

// Razor page
<form asp-action="Transfer" method="post">
    @Html.AntiForgeryToken()
    <!-- fields -->
</form>
```

For AJAX, read the token from the generated hidden field and send it as a header:

```js
const token = document.querySelector('input[name="__RequestVerificationToken"]').value;
fetch('/api/transfer', {
  method: 'POST',
  headers: {
    'RequestVerificationToken': token,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ to: 'attacker', amount: 500 })
});
```

---

## Testing & Verification

1. **Automated Scanners**  
   * **OWASP ZAP** – Use the “Active Scan” rule “Cross Site Request Forgery” to detect missing tokens.  
   * **Burp Suite** – The “CSRF PoC” extension can generate proof‑of‑concept requests automatically.

2. **Manual Checks**  
   * Attempt to submit a form from a different origin (e.g., using a local HTML file) and see if the request is accepted.  
   * Use browser dev tools to inspect cookies: ensure `SameSite` is set to `Lax` or `Strict`.  
   * Verify that all state‑changing endpoints return a **403** when the CSRF token is omitted or mismatched.

3. **CI/CD Integration**  
   * Add a step that runs `npm run test:security` or a custom script that sends crafted requests to your staging environment.  
   * Fail the build if any endpoint responds with **200** to a forged request.

---

## Best‑Practice Checklist

- [ ] **Never use GET for state‑changing actions.**  
- [ ] **Enable SameSite cookies** (`Lax` by default, `Strict` where possible).  
- [ ] **Implement the Synchronizer Token Pattern** for all POST/PUT/DELETE endpoints.  
- [ ] **Validate Origin/Referer** on critical endpoints as a secondary check.  
- [ ] **Require a custom header** (`X-Requested-With` or `X-CSRF-Token`) for AJAX calls.  
- [ ] **Store CSRF tokens securely** – use cryptographically strong random values.  
- [ ] **Rotate tokens** per request or per session to limit reuse.  
- [ ] **Avoid exposing CSRF tokens to third‑party scripts**; keep them in HTTP‑Only cookies when using double‑submit pattern only if you trust the client.  
- [ ] **Audit CORS configuration** – no wildcard `Access-Control-Allow-Origin` on authenticated routes.  
- [ ] **Add CAPTCHA or re‑authentication** for high‑value transactions.  
- [ ] **Include automated CSRF tests** in your CI pipeline.  

---

## Future Directions & Emerging Trends

1. **Browser‑Enforced CSRF Mitigation**  
   * The upcoming **SameSite=Strict by default** policy in Chrome and Edge (expected 2026) will automatically block many legacy CSRF attacks, prompting developers to migrate to POST‑based designs.

2. **Stateless Tokens with JWT Claims**  
   * Embedding a short‑lived CSRF claim inside a JWT (`csrf: <nonce>`) allows servers to validate the token without extra session storage. Frameworks like **NestJS** are experimenting with this approach.

3. **Content Security Policy (CSP) Integration**  
   * CSP can restrict the domains from which forms can be submitted (`form-action`). Combining CSP with SameSite provides defense‑in‑depth.

4. **Machine‑Learning Detection**  
   * Some WAFs now use behavioral models to flag anomalous cross‑origin POSTs that lack expected tokens, reducing reliance on static rule sets.

5. **Zero‑Trust API Gateways**  
   * API gateways that enforce **OAuth 2.0 Proof‑Key for Code Exchange (PKCE)** and **Mutual TLS** effectively eliminate CSRF because the client must prove possession of a private key, not just a cookie.

Staying ahead means **regularly reviewing browser changes**, **updating libraries**, and **re‑architecting legacy endpoints** to align with modern security expectations.

---

## Conclusion

Cross‑Site Request Forgery continues to be a potent threat because it exploits the very trust model that makes the web convenient: browsers automatically attach authentication credentials to any request matching a site’s origin. While the underlying concept is simple, the myriad ways an attacker can embed a forged request—through images, hidden forms, JSON payloads, or misconfigured CORS—make it a versatile weapon.

The most reliable defense is a **layered approach**:

1. **Set SameSite cookies** (prefer `Strict` where feasible).  
2. **Apply the synchronizer token pattern** (or double‑submit cookies) on every state‑changing endpoint.  
3. **Validate Origin/Referer** and enforce custom request headers to force preflight checks.  
4. **Harden CORS policies** and avoid permissive wildcards.  
5. **Add interaction‑based safeguards** (CAPTCHA, re‑authentication) for high‑value actions.

When combined with automated testing, CI integration, and regular audits, these measures dramatically reduce the attack surface. As browsers evolve and new standards like **stateless JWT‑embedded CSRF claims** gain traction, developers should stay vigilant, refactor legacy code, and adopt modern frameworks that embed protection by default.

By understanding both the **theory** and **practical implementation** of CSRF defenses, teams can protect users from unwanted actions, maintain trust, and keep their applications resilient against one of the web’s oldest yet still relevant attack vectors.

---

## Resources

- [OWASP Cross‑Site Request Forgery (CSRF) Prevention Cheat Sheet](https://owasp.org/www-project-cheat-sheets/cheatsheets/Cross_Site_Request_Forgery_Prevention_Cheat_Sheet.html) – Comprehensive guide on mitigation techniques.  
- [MDN Web Docs – SameSite cookies](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie/SameSite) – Browser support matrix and usage examples.  
- [RFC 6265 – HTTP State Management Mechanism](https://datatracker.ietf.org/doc/html/rfc6265) – The official specification for cookies, including SameSite.  
- [CSRF Attacks on Modern Web Applications (BlackHat 2020)](https://www.blackhat.com/docs/eu-20/materials/eu-20-Murphy-Modern-CSRF-Attacks.pdf) – Academic paper exploring advanced vectors.  
- [Spring Security Reference – CSRF Protection](https://docs.spring.io/spring-security/reference/servlet/exploits/csrf.html) – Detailed implementation in Java.  

Feel free to explore these links for deeper dives, tooling recommendations, and up‑to‑date best practices. Happy coding—securely!