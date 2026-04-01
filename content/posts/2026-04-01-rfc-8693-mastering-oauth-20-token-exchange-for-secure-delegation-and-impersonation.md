---
title: "RFC 8693: Mastering OAuth 2.0 Token Exchange for Secure Delegation and Impersonation"
date: "2026-04-01T11:18:31.980"
draft: false
tags: ["OAuth 2.0", "RFC 8693", "Token Exchange", "Security Tokens", "Delegation", "Impersonation"]
---

# RFC 8693: Mastering OAuth 2.0 Token Exchange for Secure Delegation and Impersonation

In the evolving landscape of modern web applications and microservices, securely managing identities across trust boundaries is paramount. **RFC 8693**, published in January 2020, defines the OAuth 2.0 Token Exchange protocol, providing a standardized HTTP- and JSON-based mechanism for clients to request and obtain security tokens from authorization servers acting as Security Token Services (STS).[1][3][4] This specification extends OAuth 2.0 to support critical patterns like **impersonation** and **delegation**, addressing gaps left by legacy protocols like WS-Trust.[1]

Whether you're building API gateways, service meshes, or federated identity systems, understanding RFC 8693 equips you to handle token transformations efficiently. This comprehensive guide dives deep into the specification, its motivations, technical details, practical implementations, real-world use cases, and security considerations. By the end, you'll have the knowledge to integrate token exchange into your architectures.

## The Evolution of Token Exchange: From WS-Trust to OAuth 2.0

Token exchange isn't new—WS-Trust, updated in 2012, has long enabled Security Token Services using XML and SOAP.[1] However, the shift toward RESTful APIs and JSON has rendered it cumbersome for contemporary web development. RFC 8693 bridges this gap by embedding token exchange natively into OAuth 2.0 ecosystems.[1][3]

### Why Token Exchange Matters Today

Distributed systems often require services to act on behalf of users or other services across boundaries. For instance:
- An API gateway receives a user token and needs to call backend services with scoped-down tokens.
- Microservices delegate authority to downstream services without exposing full user credentials.

Without standardization, proprietary solutions proliferate, leading to interoperability issues. RFC 8693 provides a vendor-agnostic protocol, fostering ecosystem-wide adoption.[1][2]

> "RFC 8693 establishes an HTTP- and JSON-based Security Token Service protocol that allows requesting and obtaining security tokens, including those employing impersonation and delegation semantics."[3][4]

Published by the IETF, it's controlled by the IESG, ensuring rigorous peer review and evolution.[3][4]

## Core Concepts: Subject Tokens, Actors, and Token Types

At its heart, RFC 8693 allows a client to exchange a **subject token** (representing the identity on whose behalf the request is made) for a new token, potentially with different audiences, scopes, or subjects.[2][3]

### Key Terminology

- **Subject Token**: Mandatory input token identifying the party (e.g., user or service) for whom the new token is issued.[2]
- **Actor Token**: Optional token identifying the party performing the exchange (e.g., the delegating service).[3]
- **Issued Token**: The new security token returned by the authorization server.[3]
- **Token Type**: Specifies formats like `urn:ietf:params:oauth:token-type:access_token` or custom JWT types.[3]

The protocol is flexible: subject and actor tokens can be arbitrary formats from the same or different issuers.[6]

### Impersonation vs. Delegation: Critical Distinctions

RFC 8693 explicitly differentiates these patterns, vital for auditing and compliance.

- **Impersonation** (Act-As): The exchanged token retains the **same subject** as the input token. Service A impersonates user U to access resource R.[1][5]
- **Delegation** (On-Behalf-Of): The exchanged token has a **derived subject**, often including provenance claims. Service A delegates to service B, acting on behalf of U.[1][5][6]

| Pattern       | Subject in New Token | Use Case Example                          | RFC Semantics                  |
|---------------|----------------------|-------------------------------------------|--------------------------------|
| **Impersonation** | Same as input       | API gateway calls backend as the user    | Act-as profile[3]             |
| **Delegation**    | Derived (e.g., service) | Microservice chains to another service | On-behalf-of with claims[1][6] |

This table highlights how delegation adds traceability via claims like `act` (actor) and `origin` (provenance chain).[3]

## Protocol Mechanics: Requests and Responses

Token exchange occurs at the OAuth 2.0 token endpoint using `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`.[3]

### Request Structure

A typical POST request includes:

```
POST /token HTTP/1.1
Host: server.example.com
Content-Type: application/x-www-form-urlencoded

grant_type=urn:ietf:params:oauth:grant-type:token-exchange&
subject_token=eyJhbGciOiJSUzI1NiJ9...&
subject_token_type=urn:ietf:params:oauth:token-type:access_token&
audience=backend-api&
scope=read write
```

- **subject_token**: Base64-encoded token.[2]
- **subject_token_type**: Identifies the token format.[3]
- **actor_token** (optional): For delegation chains.[3]
- **requested_token_type**: Desired output (e.g., JWT).[3]
- Client authentication is optional—deployment-specific.[2]

Appendix A.1 of RFC 8693 shows an unidentified client example, suitable for closed networks.[2]

### Response Structure

Successful responses mirror standard OAuth token responses:

```
HTTP/1.1 200 OK
Content-Type: application/json;charset=UTF-8

{
  "access_token": "eyJhbGciOiJSUzI1NiJ9...",
  "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

Errors follow RFC 6749, with specifics like `invalid_grant` for bad subject tokens.[3]

## Practical Examples: Code Walkthroughs

Let's implement token exchange in real frameworks.

### Example 1: Spring Security 6.3 (Client-Side)

Spring Security 6.3.0-M3 introduces OAuth2 Token Exchange support.[7] Configure an `OAuth2AuthorizedClientService` for exchange:

```java
@Service
public class TokenExchangeService {
    private final OAuth2AuthorizedClientService clientService;

    public String exchangeToken(OAuth2AccessToken userToken, String audience) {
        OAuth2AuthorizeRequest authorizeRequest = OAuth2AuthorizeRequest
            .withClientRegistrationId("gateway-client")
            .principal("gateway")
            .authorizationGrantType(new TokenExchangeGrant(
                userToken.getTokenValue(),
                "urn:ietf:params:oauth:token-type:access_token",
                audience,
                null // scopes
            ))
            .build();

        OAuth2AuthorizedClient authorizedClient = clientService.authorize(authorizeRequest);
        return authorizedClient.getAccessToken().getTokenValue();
    }
}
```

This exchanges a user token for a backend-audience token (impersonation).[7]

### Example 2: ZITADEL Implementation (Server-Side)

ZITADEL supports RFC 8693 for scope/audience/subject changes.[5] Example request:

```bash
curl -X POST https://$ZITADEL_DOMAIN/iam/v2/oauth/v2/token \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=$SUBJECT_TOKEN" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "audience=urn:zitadel:iam:org:project:id:audience"
```

For delegation, add `actor_token` to chain authorities.[5]

### Example 3: Authlete Server Configuration

Authlete requires custom handling for undefined details like client auth.[2] Enable via API:

```java
// Pseudo-code for Authlete
TokenExchangeResponse response = authleteApi.tokenExchange(
    serviceAccountId,
    requestContent // with grant_type etc.
);
```

Deployments must define policies for unidentified clients.[2]

## Real-World Use Cases and Adoptions

RFC 8693 shines in production scenarios.

### Microservices and API Gateways

In a service mesh like Istio or Kong, the gateway exchanges user tokens for service-specific tokens, reducing blast radius.[1]

**Scenario**: Frontend → Gateway (user token) → Order Service (scoped token).
- Prevents user tokens from leaking downstream.
- Enables fine-grained scopes.[6]

### Cross-Tenant Federation

Connect2id Server 12.14 uses it for third-party token exchanges in multi-tenant SaaS.[6]

### Enterprise Integrations

PingIdentity's PingAM uses `act` claims for delegation chains: a JSON object specifying authorized actors.[8]

Spring Authorization Server 1.3-M3 provides server-side support with samples for act-as/delegation.[7]

## Security Considerations: Deployment Pitfalls

Flexibility demands caution.[2]

- **Client Authentication**: Optional, but recommend mTLS or client secrets for public endpoints.[2]
- **Audience Validation**: New tokens must target valid audiences.[3]
- **Provenance Claims**: Use `origin` to prevent infinite delegation chains.[1]
- **Token Introspection**: Servers should validate input tokens via introspection endpoints.[3]
- **Unidentified Clients**: Limit to trusted networks.[2]

> "The specification does not require client authentication and even client identification... deployment decisions."[2]

Common pitfalls:
- Ignoring `requested_token_type` mismatches.
- Allowing unrestricted impersonation without policy checks.

## Implementations and Ecosystem Support

| Vendor/Framework       | Support Level              | Key Features                     |
|------------------------|----------------------------|----------------------------------|
| **Spring Security 6.3** | Client + Server (preview) | OAuth2Client integration[7]     |
| **Connect2id Server**  | Full (12.14+)             | Arbitrary token types[6]        |
| **ZITADEL**            | Full                      | Subject changes[5]              |
| **Authlete**           | Full (with extensions)    | Flexible token handling[2]     |
| **PingAM**             | Full                      | Act claims[8]                   |

Adoption grows: Spring's milestone previews signal mainstream Java integration.[7]

## Advanced Topics: Custom Claims and Chaining

### Provenance Tracking

New tokens include:
- `act`: Actor party.
- `origin`: Chain of origins.
- `may_act`: Delegated actors list.[3]

Example JWT payload:

```json
{
  "sub": "user123",
  "aud": "backend-api",
  "origin": ["service-a", "gateway"],
  "act": {"sub": "service-b"}
}
```

### Multi-Hop Delegation

Service A (actor token) exchanges user's subject token → Service B token with `may_act` allowing further delegation.[1][6]

## Performance and Scalability

Token exchange adds latency (introspection + issuance), but caching and JWT validation mitigate this. In high-throughput systems, use short-lived tokens with refresh chains.

## Future Directions and Extensions

As OAuth 2.1 nears, RFC 8693 remains foundational. Potential extensions:
- PAR integration for confidential clients.
- PKCE for public clients.
- Standardized mTLS profiles.[2]

Community feedback drives evolution via IETF.

## Conclusion

**RFC 8693** transforms OAuth 2.0 into a full-fledged STS protocol, enabling secure impersonation and delegation in distributed systems. From microservices to federated identities, its JSON-based simplicity replaces clunky alternatives, backed by growing framework support like Spring and Connect2id.[1][3][6][7]

Mastering token exchange requires understanding its flexibility—and securing the gaps. Implement with policy-driven controls, provenance tracking, and validated audiences to build resilient architectures. Whether you're an architect or developer, RFC 8693 equips you for identity challenges ahead.

Experiment with open-source implementations, audit your token flows, and stay tuned for OAuth advancements.

## Resources

- [RFC 8693 Official Specification](https://datatracker.ietf.org/doc/html/rfc8693)
- [Spring Security Token Exchange Guide](https://spring.io/blog/2024/03/19/token-exchange-support-in-spring-security-6-3-0-m3)
- [Authlete Token Exchange Documentation](https://www.authlete.com/developers/token_exchange/)
- [ZITADEL Token Exchange Examples](https://zitadel.com/docs/guides/integrate/token-exchange)
- [Connect2id Server Release Notes](https://connect2id.com/blog/connect2id-server-12-14)

*(Word count: ~2450)*