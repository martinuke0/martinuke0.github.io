---
title: "How One-Time Passwords (OTPs) Work — A Detailed Guide"
date: "2025-12-15T09:00:12.069"
draft: false
tags: ["authentication", "security", "OTP", "TOTP", "HOTP"]
---


One-time passwords (OTPs) are short-lived authentication codes used to verify a user or transaction and help prevent account takeover and replay attacks by being valid for only a single use or a narrow time window[1][4]. This article explains the cryptographic foundations, standardized algorithms (HOTP and TOTP), delivery methods, security tradeoffs, implementation considerations, and best practices—plus links to authoritative resources you can consult for implementation details and standards[3][4][9].

## Table of contents

- Introduction
- OTP fundamentals: what an OTP is and why it helps
- Core algorithms: HOTP and TOTP (how they work step-by-step)
- Other OTP flavors and delivery channels
- Security considerations and common attacks
- Implementation guidance and developer checklist
- User experience and operational concerns
- Further reading and authoritative resources
- Conclusion

## OTP fundamentals: what an OTP is and why it helps

- Definition: An OTP is a code generated for a single authentication event or a short time window; once used or expired it cannot be reused[1][3].  
- Purpose: OTPs add a possession factor to authentication—something the user has (device, phone, token)—complementing something they know (password) and reducing the impact of leaked static passwords[1][3].  
- Typical properties: short numeric or alphanumeric codes (commonly 6 digits), cryptographically derived from a shared secret plus a moving factor (counter or time), and validated server-side without storing reusable credentials[3][4].  

## Core algorithms: HOTP and TOTP

Both HOTP and TOTP are standardized, widely used, and form the basis of most OTP systems.

### HMAC-Based One-Time Password (HOTP)

- Overview: HOTP generates codes from a shared secret and an incrementing counter using an HMAC (commonly HMAC-SHA1)[1][3].  
- Inputs: shared secret (seed) and counter value stored by both token and server[4].  
- Algorithm (high level):
  1. Client or token and server maintain the same secret and a counter value[3].  
  2. When the token is activated (or a code requested), the token computes HMAC(secret, counter) and performs truncation to produce a short numeric code[3][4].  
  3. The server computes the expected HOTP(s) using its counter, optionally scanning a small look-ahead window to handle desynchronization, and accepts the code if it matches and hasn’t been used before[1][3].  
- Use cases: offline tokens and systems where time synchronisation is difficult; server must manage counters and replay protection[7][1].

### Time-Based One-Time Password (TOTP)

- Overview: TOTP replaces the counter with the current time (usually in 30-second steps) and is the most common modern OTP type[1][3][6].  
- Inputs: shared secret and current time step (derived from Unix time divided by a step size, e.g., 30s)[3][6].  
- Algorithm (high level):
  1. Both token (authenticator app or device) and server hold the same secret and compute the time-step value from the current time[3][6].  
  2. They compute HMAC(secret, time-step) and truncate to a numeric code (often 6 digits)[3][4].  
  3. Servers usually accept codes from the current and adjacent time steps (±1) to allow for clock drift[3].  
- Practical notes: TOTPs are typically valid for 30–60 seconds and provide narrow windows of exposure, making automated attacks harder[1][6].

Sources describing these algorithms and their steps include Okta, Auth0, WorkOS and standards-oriented references[1][3][4][9].

## Other OTP flavors and delivery channels

- SMS and email OTPs: Server-generated OTPs delivered over SMS or email for immediate use; simple to implement but vulnerable to SIM swap, interception, and phishing[2][5].  
- Push-based OTP / Push notifications: Instead of entering a code, a push message prompts the user to confirm a login; often more user-friendly and resistant to simple replay but requires secure push channel and device integrity.  
- Hardware tokens (OTP fobs, smartcards): Devices that compute HOTP/TOTP locally and display codes; more resistant to remote compromise but can be lost or stolen[4].  
- Biometrics + OTP: OTPs combined with biometric checks on device add protection but increase complexity.  
- Static “single-use” links: Systems send a one-time login link (magic link) to an email; functionally an OTP tied to a URL and expiry[5].

## Security considerations and common attacks

- Replay attacks: HOTP requires careful counter management and one-time use checks to avoid replay; TOTP’s short validity window reduces replay risk but not to zero[3][1].  
- Phishing: OTPs entered into malicious pages can be used immediately by attackers (real-time relay); phish-resistant MFA methods (FIDO/WebAuthn, hardware tokens with attestation) are stronger[9].  
- SIM swap and SMS interception: SMS OTPs are vulnerable to carrier-level attacks and social engineering; industry guidance recommends avoiding SMS for high-risk transactions[2][5].  
- Man-in-the-middle (MITM): Sophisticated MITM can capture and forward OTPs in real time; push notifications and hardware-backed authenticators mitigate this better than SMS[9].  
- Clock drift and synchronization: TOTP servers must allow small tolerance (±1 time step) to accommodate client clock drift; larger windows weaken security[3][6].  
- Secret management: Secure generation, storage (hardware security modules or secure enclaves), and rotation of shared secrets are critical to prevent token cloning[4].

## Implementation guidance and developer checklist

- Choose algorithm: Prefer TOTP for standard user-facing authenticators (mobile apps, hardware tokens); use HOTP when offline operation is required[3][7].  
- Secret provisioning: Use secure QR-code provisioning for authenticator apps (e.g., otpauth:// URIs) and ensure secrets are generated with sufficient entropy and transmitted over TLS[3][4].  
- Clock sync: Ensure server time is synced via NTP and accept a small validation window (commonly ±30–60 seconds) for TOTP[3][6].  
- Replay protection: Mark a code as used once accepted (especially for HOTP) and prevent reuse within the validity window[3].  
- Rate limiting and throttling: Limit OTP submission attempts and throttle/respect exponential backoff to mitigate brute force attempts[9].  
- Delivery channel security: Avoid SMS for high-risk actions; if used, couple with monitoring for SIM swap indicators and additional checks[2][5].  
- Logging and monitoring: Log OTP failures and unusual patterns (many different codes, frequent requests) and alert on suspicious activity[9].  
- Backup and recovery: Provide secure account recovery paths (e.g., backup codes, registered hardware tokens) in case the user loses access to the authenticator; protect recovery methods strongly[4].  
- Consider phishing-resistant options: Where possible, adopt FIDO2/WebAuthn or hardware-backed attestation to defeat real-time phishing and MITM[9].

### Minimal TOTP example (conceptual pseudocode)

```python
# Conceptual TOTP generation flow (do not use as-is in production)
import hmac, hashlib, time

def totp(secret, digits=6, timestep=30, algo=hashlib.sha1):
    t = int(time.time() / timestep)
    # compute HMAC(secret, t) where secret is bytes and t is 8-byte big-endian
    msg = t.to_bytes(8, 'big')
    h = hmac.new(secret, msg, algo).digest()
    # dynamic truncation
    offset = h[-1] & 0x0F
    code = (int.from_bytes(h[offset:offset+4], 'big') & 0x7fffffff) % (10**digits)
    return str(code).zfill(digits)
```

Refer to standards and libraries for production-ready, vetted implementations rather than rolling your own[3][4].

## User experience and operational concerns

- UX tradeoffs: Shorter windows (30s) increase security but may frustrate users; allow clear instructions and easy copy/paste for codes[1].  
- Accessibility: Provide alternatives for users who cannot use mobile apps (hardware tokens, assistive device-friendly flows).  
- Rate of challenge: Decide when to require OTPs—every login, only new devices, high-risk transactions, or adaptive risk-based triggers for best balance between security and friction[1][5].  
- Support and recovery: Offer pre-generated backup codes or registered secondary devices, and robust, verified account recovery to avoid lockouts[4].

## Further reading and authoritative resources

- Okta — “One Time Password: How OTP Authentication Works” (detailed explanation of TOTP/HOTP, shared secrets, and validation windows)[1].  
- Auth0 — “What is a One Time Password (OTP)” (practical enrollment and seed/moving factor explanation)[4].  
- WorkOS — “One-Time Passwords (OTPs) explained” (developer-focused guide with algorithm steps and sample flows)[3].  
- MDN Web Docs — “One-time passwords (OTP)” (security overview and temporal components)[9].  
- Fraud.com and Vibes — practical overviews of OTP delivery channels and UX considerations[2][5].  
- NIST and relevant RFCs: For production systems consult standards such as RFC 4226 (HOTP) and RFC 6238 (TOTP) for formal algorithm definitions (these are the de-facto references; see the RFC repository for the exact texts).

## Conclusion

OTPs are a well-understood, practical mechanism to add a possession factor to authentication by generating short-lived, single-use codes using either a counter (HOTP) or time (TOTP) combined with a shared secret[3][1]. TOTP is the dominant modern approach due to its simplicity and narrow exposure window, while HOTP remains useful for offline tokens[1][7]. Security depends less on the concept of OTP and more on implementation choices: delivery channel, secret provisioning and protection, replay prevention, clock synchronization, and resistance to phishing and SIM-swap attacks[2][9]. For production use follow established standards (RFC 4226, RFC 6238), use vetted libraries, avoid SMS for high-risk flows when possible, and consider stronger, phishing-resistant alternatives like FIDO/WebAuthn where appropriate.

> Important note: For implementation, rely on well-maintained cryptographic libraries and consult the referenced vendor/standards documentation for exact parameters, test vectors, and secure provisioning details[3][4][1].

