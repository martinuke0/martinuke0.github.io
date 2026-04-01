---
title: "Understanding OAuth 2.0 Token Exchange (RFC 8693) and Delegation Grants"
date: "2026-04-01T13:33:13.162"
draft: false
tags: ["OAuth2", "Token Exchange", "RFC8693", "Delegation", "Security"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Why Token Exchange Exists](#why-token-exchange-exists)  
3. [The Core Concepts of RFC 8693](#the-core-concepts-of-rfc8693)  
   - 3.1 [Actors and Roles](#actors-and-roles)  
   - 3.2 [Grant Types and Token Types](#grant-types-and-token-types)  
4. [Protocol Flow in Detail](#protocol-flow-in-detail)  
   - 4.1 [Step‑by‑Step Request/Response Walk‑through](#step‑by‑step-requestresponse-walkthrough)  
   - 4.2 [Message Parameters Explained](#message-parameters-explained)  
5. [Practical Use‑Cases](#practical-use-cases)  
   - 5.1 [Service‑to‑Service Delegation](#service-to-service-delegation)  
   - 5.2 [Impersonation & On‑Behalf‑Of (OBO)](#impersonation--on-behalf-of-obo)  
   - 5.3 [Cross‑Domain Identity Propagation](#cross-domain-identity-propagation)  
   - 5.4 [Legacy System Integration (SAML ↔ JWT)](#legacy-system-integration-saml--jwt)  
6. [Implementing Token Exchange](#implementing-token-exchange)  
   - 6.1 [Using Keycloak](#using-keycloak)  
   - 6.2 [Using Hydra (ORY)](#using-hydra-ory)  
   - 6.3 [Azure AD & Microsoft Identity Platform](#azure-ad--microsoft-identity-platform)  
   - 6.4 [Sample cURL & Python Code](#sample-curl--python-code)  
7. [Security Considerations](#security-considerations)  
   - 7.1 [Audience Restriction & Token Binding](#audience-restriction--token-binding)  
   - 7.2 [Replay Protection & JTI](#replay-protection--jti)  
   - 7.3 [Scope Limiting & Principle of Least Privilege](#scope-limiting--principle-of-least-privilege)  
8. [Common Pitfalls & Troubleshooting](#common-pitfalls--troubleshooting)  
9. [Future Directions & Extensions](#future-directions--extensions)  
10. [Conclusion](#conclusion)  
11. [Resources](#resources)

---

## Introduction

OAuth 2.0 has become the de‑facto standard for delegated authorization on the web. Its original grant types—authorization code, client credentials, resource owner password credentials, and implicit—address many classic scenarios, but modern micro‑service architectures, multi‑tenant SaaS platforms, and hybrid cloud‑on‑prem environments often demand more flexible token handling.  

Enter **OAuth 2.0 Token Exchange**, defined in **RFC 8693**. The specification introduces a new **grant type**—`urn:ietf:params:oauth:grant-type:token-exchange`—that allows a client (or service) to exchange one security token for another, possibly with a different format, audience, or set of claims. In practice, token exchange powers **delegation grants**, **on‑behalf‑of** (OBO) flows, and cross‑domain identity propagation.

This article provides a deep dive into token exchange: the rationale behind it, the mechanics defined by RFC 8693, concrete implementation examples, security best practices, and real‑world usage patterns. By the end, you should be able to design, implement, and secure a token‑exchange endpoint that meets the needs of sophisticated distributed systems.

---

## Why Token Exchange Exists

### The Gap in Classic OAuth

Classic OAuth grants assume a *single* token that travels from the client to the resource server. However, several real‑world constraints break this assumption:

| Scenario | Problem with Classic OAuth | How Token Exchange Helps |
|----------|----------------------------|--------------------------|
| **Service‑to‑Service Calls** | Service A holds a token issued to it, but Service B expects a token issued by its own identity provider (different audience). | A can exchange its token for a token scoped to Service B’s audience. |
| **Impersonation** | A front‑end UI wants to act on behalf of an end‑user when calling a back‑end API. | UI exchanges the user’s access token for an OBO token that the back‑end trusts. |
| **Legacy Integration** | Older services accept SAML assertions, while modern services use JWTs. | Token exchange bridges format gaps (e.g., SAML → JWT). |
| **Multi‑Tenant SaaS** | Tenants have isolated identity providers; a central gateway must translate tokens per tenant. | Gateway exchanges the inbound token for a tenant‑specific token. |
| **Reduced Scope** | A client may have a broad token but only needs a narrow subset for a particular operation. | Exchange can produce a token with a reduced scope, limiting exposure. |

### Delegation Grants: A Precise Term

In the OAuth literature, the term **delegation grant** often describes the act of granting a downstream service *limited* authority on behalf of an upstream principal. Token exchange is the protocol that enables such delegation, making it a cornerstone of zero‑trust and least‑privilege designs.

---

## The Core Concepts of RFC 8693

RFC 8693 builds on the existing OAuth framework but adds several new concepts.

### Actors and Roles

| Actor | Role in Token Exchange |
|-------|------------------------|
| **Client** | The entity that initiates the exchange request. It can be a confidential client (e.g., a back‑end service) or a public client (e.g., a SPA). |
| **Authorization Server (AS)** | Holds the token‑exchange endpoint (`/token`) and performs validation, mapping, and issuance of the new token. |
| **Resource Server (RS)** | The ultimate consumer of the exchanged token. It validates the token’s audience, scopes, and claims. |
| **Subject Token** | The token presented for exchange (e.g., an access token, ID token, SAML assertion). |
| **Requested Token** | The token the client wishes to receive (e.g., an access token for a different audience). |

The specification also defines **actor tokens**, which can be used to prove the client’s identity during the exchange (e.g., a client‑asserted JWT).

### Grant Types and Token Types

- **Grant Type**: `urn:ietf:params:oauth:grant-type:token-exchange`
- **Token Types**: Any format that both the AS and RS understand. Common types:
  - `urn:ietf:params:oauth:token-type:access_token` (opaque or JWT)
  - `urn:ietf:params:oauth:token-type:id_token`
  - `urn:ietf:params:oauth:token-type:refresh_token`
  - `urn:ietf:params:oauth:token-type:saml2` (SAML assertions)
  - `urn:ietf:params:oauth:token-type:jwt`

---

## Protocol Flow in Detail

### Step‑by‑Step Request/Response Walk‑through

1. **Client obtains a *subject token*** from an upstream flow (e.g., user login, client credentials, or another exchange).  
2. **Client calls the token endpoint** of the AS with the `grant_type` set to `token-exchange`.  
3. **AS validates** the subject token, checks any required actor token, and verifies that the requested token type and audience are permissible.  
4. **AS issues the *requested token*** and returns it in a standard OAuth token response.  
5. **Client forwards the requested token** to the target RS, which treats it as a regular access token.

### Message Parameters Explained

| Parameter | Required? | Description |
|-----------|-----------|-------------|
| `grant_type` | Yes | Must be `urn:ietf:params:oauth:grant-type:token-exchange`. |
| `subject_token` | Yes | The token being exchanged. |
| `subject_token_type` | Yes | A URI indicating the format of `subject_token`. |
| `resource` | No | Target resource(s) the requested token is intended for (audience). |
| `audience` | No | Desired audience for the requested token; often matches `resource`. |
| `scope` | No | Scopes to be associated with the requested token. |
| `requested_token_type` | No | Desired format of the new token (defaults to access token). |
| `actor_token` | No | Token proving the client’s identity (e.g., client JWT). |
| `actor_token_type` | No | URI indicating the format of `actor_token`. |
| `options` | No | Additional implementation‑specific options (e.g., `"access_token_format": "jwt"`). |

**Example HTTP request (cURL)**:

```bash
curl -X POST https://auth.example.com/oauth2/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "client_id:client_secret" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "audience=https://api.service-b.example.com" \
  -d "scope=read:data write:data"
```

**Typical success response**:

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scope": "read:data write:data"
}
```

---

## Practical Use‑Cases

### Service‑to‑Service Delegation

**Scenario**: Service A (running in Kubernetes) receives a JWT from an upstream identity provider (IdP). It must call Service B, which trusts a different IdP and expects tokens issued by `auth.service-b.example.com`.

**Solution**: Service A uses token exchange to obtain a Service‑B‑specific token, thereby preserving least‑privilege and avoiding token leakage across trust boundaries.

### Impersonation & On‑Behalf‑Of (OBO)

**Scenario**: A mobile app authenticates a user via an OAuth authorization code flow, obtaining an access token for the mobile backend. The backend then needs to call a downstream accounting API on behalf of the same user.

**Solution**: The backend performs an OBO token exchange, passing the user’s original access token as `subject_token` and requesting a token whose `audience` is the accounting API. The accounting API sees a token whose `sub` claim matches the user’s identifier, enabling fine‑grained audit trails.

### Cross‑Domain Identity Propagation

**Scenario**: A federation of partner companies shares resources via a central API gateway. Each partner uses its own IdP (Azure AD, Okta, Ping). The gateway must translate incoming tokens into a unified format for internal services.

**Solution**: The gateway validates the inbound token, then uses token exchange with a *trusted* internal AS to issue a canonical JWT that internal services recognize. The `audience` claim is set to the internal service’s identifier, and the `iss` claim points to the internal AS.

### Legacy System Integration (SAML ↔ JWT)

Many enterprises still run SOAP‑based services that accept SAML assertions. Modern APIs, however, prefer JWTs.

**Approach**:
1. Obtain a SAML assertion from the legacy IdP (perhaps via WS‑Trust).  
2. Submit it to an OAuth AS that supports `subject_token_type=urn:ietf:params:oauth:token-type:saml2`.  
3. Request a JWT (`requested_token_type=urn:ietf:params:oauth:token-type:jwt`).  
4. Use the resulting JWT to call modern REST endpoints, while the legacy service continues to accept the original SAML assertion.

---

## Implementing Token Exchange

Below we walk through three popular open‑source and commercial platforms that support RFC 8693.

### Using Keycloak

Keycloak (v21+) includes a built‑in **Token Exchange** provider.

1. **Enable the feature**  
   - Navigate to **Realm Settings → Tokens → Token Exchange**.  
   - Turn on *Allow Token Exchange* and configure allowed `client_ids` for both the *source* and *target* clients.

2. **Define clients**  
   - **Source client** (`frontend-app`) obtains a user access token via standard OIDC.  
   - **Target client** (`service-b`) is configured as *confidential* with a client secret.

3. **Exchange request** (cURL example):

```bash
curl -X POST https://keycloak.example.com/realms/myrealm/protocol/openid-connect/token \
  -u "frontend-app:frontend-secret" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=${USER_ACCESS_TOKEN}" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "audience=service-b"
```

Keycloak returns a JWT signed with its realm’s private key. You can also request a *refresh token* by adding `requested_token_type=urn:ietf:params:oauth:token-type:refresh_token`.

### Using Hydra (ORY)

Hydra implements the **OAuth 2.0 Token Exchange** as an optional **extension**. To enable:

```bash
hydra serve all \
  --token-exchange-enabled=true \
  --issuer-url=https://hydra.example.com
```

Hydra expects a **policy decision point (PDP)** to decide whether a given exchange is allowed. The policy can be expressed in JSON:

```json
{
  "subject_token_issuer": "https://idp.example.com",
  "allowed_audiences": ["https://api.service-b.example.com"],
  "allowed_scopes": ["read", "write"]
}
```

Hydra’s request format matches the standard RFC 8693 parameters.

### Azure AD & Microsoft Identity Platform

Azure AD introduced **On‑Behalf‑Of (OBO)** flow, which is essentially token exchange. The endpoint is the same `/token` endpoint used for other grants.

**Key differences**:
- `grant_type` is `urn:ietf:params:oauth:grant-type:jwt-bearer`.
- The `assertion` parameter carries the *subject token* (the user’s access token).
- `requested_token_use=on_behalf_of` signals an OBO exchange.

**Example** (using `az` CLI to acquire an OBO token):

```bash
az account get-access-token \
  --resource https://graph.microsoft.com \
  --query accessToken -o tsv
```

Internally, Azure AD validates the incoming token, checks the client’s delegated permissions, and returns a new token scoped to the target resource.

### Sample cURL & Python Code

#### cURL (Generic)

```bash
curl -X POST https://as.example.com/oauth2/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "client-id:client-secret" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=${SUBJECT_TOKEN}" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "requested_token_type=urn:ietf:params:oauth:token-type:jwt" \
  -d "audience=https://api.target.example.com" \
  -d "scope=read write"
```

#### Python (Requests)

```python
import requests
from requests.auth import HTTPBasicAuth

TOKEN_ENDPOINT = "https://as.example.com/oauth2/token"
CLIENT_ID = "my-client"
CLIENT_SECRET = "s3cr3t"
SUBJECT_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."

payload = {
    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
    "subject_token": SUBJECT_TOKEN,
    "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
    "requested_token_type": "urn:ietf:params:oauth:token-type:jwt",
    "audience": "https://api.target.example.com",
    "scope": "read write"
}

resp = requests.post(
    TOKEN_ENDPOINT,
    data=payload,
    auth=HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)
)

resp.raise_for_status()
new_token = resp.json()["access_token"]
print("Exchanged token:", new_token)
```

---

## Security Considerations

Token exchange introduces additional attack surfaces; careful design mitigates risk.

### Audience Restriction & Token Binding

- **Validate `audience`/`resource`**: The AS must ensure the requested audience is permitted for the client and for the original subject token.  
- **Token Binding**: Some deployments bind the exchanged token to a TLS certificate or a client secret, preventing token reuse by a different party.

> **Note:** If the AS issues JWTs, include a `cnf` (confirmation) claim that references the client’s public key or a token‑binding identifier.

### Replay Protection & JTI

- **JTI (JWT ID)**: Include a unique identifier and store used JTIs for a short window (e.g., 5 minutes).  
- **Nonce**: When the subject token is an ID token, a `nonce` claim can be cross‑checked during exchange.

### Scope Limiting & Principle of Least Privilege

- **Never broaden scopes**: The exchanged token must never have a superset of the original token’s scopes unless explicitly authorized.  
- **Scope Reduction**: Use the `scope` parameter to request a minimal set needed for the downstream call.

> **Best practice:** Adopt a policy‑engine (OPA, XACML) that evaluates `subject_token`, `client_id`, `audience`, and requested `scope` before issuing a token.

### Confidentiality of Actor Tokens

If an **actor token** is used (e.g., client‑asserted JWT), protect it with strong signing algorithms (RS256 or ES256) and short expiration times. Do **not** transmit actor tokens in URLs.

### Auditing & Logging

- Log every exchange request with: client ID, subject token hash (e.g., SHA‑256), audience, scopes, and outcome.  
- Retain logs for at least 90 days to support forensic investigations.

---

## Common Pitfalls & Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `invalid_grant` response | Subject token expired or malformed | Verify token signature, expiry (`exp`), and ensure correct `subject_token_type`. |
| `unsupported_token_type` | AS does not support the requested token format | Check AS documentation; enable JWT output or install required token‑type plugins. |
| Audience mismatch error | `audience` not whitelisted for client | Update client’s allowed audiences in AS configuration. |
| 401 Unauthorized despite correct client secret | Missing `actor_token` when AS requires client authentication via JWT | Provide a signed client assertion (`client_assertion` & `client_assertion_type`). |
| Token size exceeds header limits | Exchanged JWT is too large (many claims) | Trim unnecessary claims; use `claims` parameter to request specific claim set. |

**Debugging tip**: Use JWT.io to decode both the subject and exchanged tokens. Compare the `iss`, `sub`, `aud`, and `scope` claims to ensure they align with policy expectations.

---

## Future Directions & Extensions

- **RFC 9421 (OAuth 2.0 Token Introspection Enhancements)** may enable richer introspection of exchanged tokens, facilitating dynamic revocation.  
- **Token Binding (RFC 8471)** integration could make exchanges *zero‑knowledge* with respect to the client, improving resistance to token theft.  
- **Decentralized Identity (DID) & Verifiable Credentials**: Emerging frameworks may use token exchange to translate verifiable credentials into OAuth access tokens for legacy services.  
- **Policy‑Driven Exchanges**: Projects like *OPA‑OAuth* aim to embed Rego policies directly into the token‑exchange decision point, offering fine‑grained, context‑aware authorizations.

---

## Conclusion

OAuth 2.0 Token Exchange (RFC 8693) fills a critical gap in modern distributed architectures by allowing a client to transform, delegate, or narrow the authority of an existing token. Whether you’re building a micro‑service mesh, enabling on‑behalf‑of flows for mobile back‑ends, or bridging legacy SAML systems with JWT‑centric APIs, token exchange offers a standards‑based, interoperable solution.

Key takeaways:

- **Understand the actors** – subject token, requested token, and optional actor token.  
- **Validate audience, scope, and token type** rigorously to prevent privilege escalation.  
- **Leverage existing platforms** (Keycloak, Hydra, Azure AD) that already implement the spec, reducing custom development effort.  
- **Apply security best practices**: token binding, JTI replay protection, least‑privilege scopes, and thorough auditing.  
- **Stay aware of emerging extensions** that will further enhance token exchange’s capabilities in zero‑trust environments.

By thoughtfully integrating token exchange into your security architecture, you empower services to communicate securely while preserving the principle of least privilege—an essential cornerstone of any robust, future‑ready system.

---

## Resources
- [RFC 8693 – OAuth 2.0 Token Exchange](https://datatracker.ietf.org/doc/html/rfc8693)  
- [OAuth 2.0 Authorization Framework (RFC 6749)](https://datatracker.ietf.org/doc/html/rfc6749)  
- [Keycloak Documentation – Token Exchange](https://www.keycloak.org/docs/latest/securing_apps/#token-exchange)  
- [ORY Hydra – Token Exchange Extension](https://www.ory.sh/hydra/docs/reference/api#token-exchange)  
- [Microsoft Identity Platform – On‑Behalf‑Of Flow](https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-on-behalf-of-flow)  
- [IETF Token Binding (RFC 8471)](https://datatracker.ietf.org/doc/html/rfc8471)  

---