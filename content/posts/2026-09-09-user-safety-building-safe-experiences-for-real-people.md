

---
title: "User Safety: Building Safe Experiences for Real People"
date: "2026-09-09T23:01:14.209"
draft: false
tags: ["user-safety", "security", "privacy", "engineering", "trust", "ux"]
description: "Practical strategies for building user-safe software, from authentication to abuse prevention. Learn how to protect real people in production systems."
summary: "User safety is not a feature—it's a foundation. This post explores concrete patterns for authentication, authorization, and abuse prevention that engineering teams can implement today."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-09-user-safety-building-safe-experiences-for-real-people.svg"
  alt: "Abstract illustration of a shield protecting a user interface"
  caption: ""
  relative: false
---

> **TL;DR** — User safety is not a single feature but a system of interlocking patterns. From authentication to abuse prevention, this post breaks down the concrete engineering decisions that keep real people safe in production. You'll learn how to layer defenses, enforce least privilege, and build monitoring that catches problems before users feel them.

In 2021, a security researcher found that a popular fitness app exposed private workout data to anyone with a user ID. The fix wasn't a single line of code—it was a fundamental rethinking of how the team approached safety. Yet many engineering teams still treat user safety as a compliance checkbox rather than an architectural principle. This post argues that safety belongs in the design phase, not in a post-launch audit. We'll walk through the patterns that matter, with concrete tools and production scenarios you can apply immediately.

## Why User Safety Is an Engineering Problem, Not a Compliance Checkbox

Regulatory frameworks like GDPR and CCPA push companies to "protect user data," but the resulting checklists often produce brittle, superficial controls. A real safety culture means designing for the adversary: the script kiddie brute-forcing login endpoints, the insider with excessive database access, or the automated bot scraping your API for competitive intelligence.

The difference between a safe system and a merely compliant one is **defense in depth**. No single control stops every attack. Instead, you layer authentication, authorization, encryption, rate limiting, and monitoring so that if one layer fails, the next catches the threat. This pattern mirrors production reliability: you don't rely on one database; you shard, replicate, and monitor. Safety works the same way.

## Authentication: The First Line of Defense

Authentication is where most user-facing attacks begin. Weak passwords, session fixation, and credential stuffing remain the top vectors because they're easy to exploit and hard to detect. The good news: modern patterns have matured enough that you can ship world-class authentication without building it from scratch.

### Passwordless and WebAuthn

Passwordless authentication removes the password entirely, eliminating credential stuffing and phishing. WebAuthn, standardized by the [FIDO Alliance](https://fidoalliance.org/specifications/), lets users authenticate with platform authenticators (Touch ID, Windows Hello) or security keys. The protocol is supported by all major browsers and is simpler to implement than custom password logic.

```python
# Example: Verifying a WebAuthn assertion in Python
# Using the webauthn library (pip install webauthn)
from webauthn import verify_assertion_response
from webauthnAssertionResponse import AssertionResponse

# The assertion response comes from the browser's navigator.credentials.get()
assertion = AssertionResponse(
    id=base64url_decode(response["id"]),
    raw_id=base64url_decode(response["rawId"]),
    authenticator=AuthenticatorAssertionResponse(
        client_data_json=response["response"]["clientDataJSON"],
        authenticator_data=response["response"]["authenticatorData"],
        signature=response["response"]["signature"],
    ),
)

verified = verify_assertion_response(
    assertion=assertion,
    credential_public_key=stored_credential_public_key,
    expected_origin="https://yourapp.com",
    expected_rp_id="yourapp.com",
)
```

If you can't adopt WebAuthn today, at minimum enforce multi-factor authentication (MFA) for every account. TOTP via apps like Authy or Google Authenticator is a reasonable fallback. The [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) recommends rejecting passwords that appear in known breach corpora—tools like [Have I Been Pwned](https://haveibeenpwned.com/API/v3) make this a one-line check.

### Session Management

Once authenticated, sessions are the next attack surface. Never store session tokens in cookies without `HttpOnly`, `Secure`, and `SameSite=Strict` flags. Rotate session IDs after login to prevent session fixation. For long-lived sessions, implement refresh token rotation: issue a new refresh token with each access token and invalidate the old one. This limits the blast radius if a token leaks.

```yaml
# Example: Secure cookie configuration in an nginx reverse proxy
# This ensures tokens are never transmitted over plaintext HTTP
add_header Set-Cookie "session=${TOKEN}; HttpOnly; Secure; SameSite=Strict; Max-Age=3600" always;
```

## Authorization: Least Privilege and Beyond

Authentication answers "who are you?" Authorization answers "what can you do?" The principle of least privilege—granting users only the permissions they need—sounds obvious, but it's routinely violated in production. A customer service agent shouldn't need direct database access, yet I've seen support teams with `SELECT *` privileges on customer tables.

### Role-Based Access Control (RBAC)

Start with RBAC: assign permissions to roles, assign roles to users. Keep the role hierarchy flat; deeply nested roles become unmanageable and create privilege escalation paths. For most SaaS products, five roles cover 90% of use cases: `admin`, `member`, `viewer`, `auditor`, and `support`.

### Attribute-Based Access Control (ABAC)

As products grow, RBAC becomes too coarse. ABAC makes decisions based on attributes: user attributes (department, seniority), resource attributes (owner, sensitivity), and environment attributes (time of day, IP range). The open source [Open Policy Agent (OPA)](https://www.openpolicyagent.com/) lets you express ABAC policies in Rego, a declarative language:

```rego
# Allow a user to read a document only if they own it or are in the same team
allow {
    input.user.id == input.resource.owner_id
}

allow {
    input.user.team == input.resource.team
    input.method == "GET"
}
```

OPA integrates with Go, Python, and Node.js services via a sidecar or library, making it a drop-in replacement for hardcoded `if` checks.

## Privacy: Data Minimization and Encryption

Safety isn't just about preventing unauthorized access—it's also about collecting only what you need and handling it responsibly. Data minimization reduces the value of your database to attackers and limits regulatory exposure.

### Encryption at Rest and in Transit

Use TLS 1.3 everywhere. For data at rest, encrypt sensitive columns (PII, tokens) with envelope encryption: a data encryption key (DEK) encrypts the data, and a key encryption key (KEK) wraps the DEK. Cloud providers like AWS KMS and GCP Cloud KMS handle KEK rotation for you.

```python
# Example: Encrypting a user's email before storing in Postgres
from cryptography.fernet import Fernet
import base64

# The DEK is stored in the database; the KEK wraps/unwraps it via KMS
def encrypt_value(plaintext: str, dek: bytes) -> str:
    fernet = Fernet(dek)
    return base64.urlsafe_b64encode(fernet.encrypt(plaintext.encode())).decode()
```

### Anonymization and Retention

If you can identify a user, you've collected more data than necessary. Anonymize analytics data by hashing identifiers with a secret salt before aggregation. Set explicit retention policies and automate deletion. A user who closes their account should trigger a cascade that removes their data from backups within the retention window, not years later.

## Abuse Prevention: Rate Limiting, CAPTCHA, and Content Moderation

Even authenticated users can behave abusively. Rate limiting is your first firewall. Use a sliding-window algorithm with Redis for per-IP and per-user limits. For example, allow 10 login attempts per 15 minutes per IP; after that, return a 429 and log the event.

```python
# Example: Sliding-window rate limiter in Python with Redis
import redis
import time

r = redis.Redis(host='localhost', port=6379)

def check_rate_limit(key: str, limit: int, window: int) -> bool:
    """Return True if the request is allowed."""
    now = time.time()
    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)  # Remove expired entries
    pipe.zadd(key, {now: now})                     # Add current request
    pipe.zcard(key)                                # Count requests in window
    pipe.expire(key, window + 1)                   # Set TTL
    count = pipe.execute()[-1]
    return count <= limit
```

For content moderation, combine automated filters ( profanity lists, image classifiers) with human review queues. Services like [Google Cloud Perspective API](https://cloud.google.com/toxicity-moderation) or AWS Comprehend can flag toxic text, but always include a human-in-the-loop for edge cases. The goal isn't perfection—it's catching the worst abuse before it reaches your users.

## Monitoring and Incident Response

You can't fix what you don't see. Instrument every safety-critical path: authentication attempts, authorization denials, rate limit hits, and content moderation actions. Ship logs to a centralized system like [ELK Stack](https://www.elastic.co/elastic-stack) or [Datadog](https://www.datadog.com/), and create dashboards that surface anomalies. A sudden spike in 403 responses might indicate a broken permission change; a surge in rate limit rejections could signal a botnet.

When an incident occurs, have a runbook. The [NIST SP 800-61](https://csrc.nist.gov/publications/detail/sp/800-61/rev/2/final) guide for incident handling provides a solid framework: prepare, detect, contain, eradicate, recover, and learn. Post-mortems should focus on systemic fixes, not individual blame.

## Key Takeaways

- **Safety is architectural, not cosmetic.** Treat it as a design constraint, not a post-hoc audit item.
- **Layer defenses.** Combine authentication, authorization, encryption, rate limiting, and monitoring so no single failure exposes users.
- **Adopt modern authentication.** Passwordless and WebAuthn eliminate entire classes of attacks. If you can't, enforce MFA and reject breached passwords.
- **Enforce least privilege.** Use RBAC or ABAC to ensure users can only access what they need, when they need it.
- **Minimize data.** Collect only what you use, encrypt what you store, and automate retention.
- **Monitor relentlessly.** Build dashboards for safety metrics and runbooks for incidents. A safe system is a visible system.

## Further Reading

- [OWASP Top Ten](https://owasp.org/www-project-top-ten/) — The canonical list of the most critical web application security risks.
- [NIST SP 800-63B: Digital Identity Guidelines](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-63b.pdf) — Recommendations for authentication and lifecycle management.
- [Open Policy Agent (OPA)](https://www.openpolicyagent.com/) — Policy-based access control for microservices and APIs.
- [Have I Been Pwned API](https://haveibeenpwned.com/API/v3) — Check passwords against known breach datasets.
- [Google Cloud Perspective API](https://cloud.google.com/toxicity-moderation) — Automated content moderation for user-generated text.