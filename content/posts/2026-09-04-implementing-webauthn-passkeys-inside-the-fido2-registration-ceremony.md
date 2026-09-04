---
title: "Implementing WebAuthn Passkeys: Inside the FIDO2 Registration Ceremony"
date: "2026-09-04T09:00:46.023"
draft: false
tags: ["webauthn", "passkeys", "fido2", "authentication", "security"]
description: "A hands-on guide to implementing FIDO2 WebAuthn passkeys, breaking down the registration ceremony from challenge generation to attestation."
summary: "Inside the WebAuthn registration ceremony: how challenges are minted, how authenticators create key pairs, and what your backend needs to verify."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-implementing-webauthn-passkeys-inside-the-fido2-registration-ceremony.svg"
  alt: "Abstract diagram of cryptographic key exchange between browser, authenticator, and server."
  caption: ""
  relative: false
---

> **TL;DR** — The WebAuthn registration ceremony is a four-party handshake between the user, browser, authenticator, and relying party that produces a public key bound to an account. Implement it by generating a server-side challenge, serializing it with `PublicKeyCredentialCreationOptions`, letting the authenticator mint a key, and verifying the returned attestation against your stored credential.

Passwords are a liability. They get phished, sprayed, reused, and leaked. WebAuthn — the browser API behind passkeys — replaces that liability with public-key cryptography. A passkey is just a credential whose private key never leaves the user's device, can't be phished because it's bound to the origin, and can be synced across the user's own devices via iCloud Keychain, Google Password Manager, or 1Password.

If you're a backend engineer tasked with wiring this up, the registration half of the ceremony is the most important thing to get right, because once a credential is registered badly, every subsequent login inherits the rot. This post walks through the entire registration flow end-to-end, with the protocol framing, the JSON shapes, the cryptographic checks, and the failure modes you actually need to defend against.

## Why Passkeys, and Why Now

The ecosystem has caught up. Apple added [platform passkey support](https://developer.apple.com/passkeys/) in 2022; Google rolled out [passkey support in Chrome and Password Manager](https://developers.google.com/identity/passkeys) shortly after. By 2025, the major browsers converge on the same CTAP2 / WebAuthn Level 3 specification, and FIDO Alliance has published the [WebAuthn Level 3 editor's draft](https://fidoalliance.org/specs/webauthn-spec-v3.0-ps-20241127.html) that defines the current shape of the ceremony.

For your relying party (RP) — that's you, the server — the practical wins are:

- **No password database.** You store a public key, a credential ID, and a signature counter. There's nothing to hash, nothing to leak.
- **Phishing-resistant by construction.** The credential is bound to the origin (RP ID). A clone of your site on `evil.example` cannot trigger a signature that your RP will accept.
- **Resistance to credential stuffing.** There's no shared secret to spray across accounts.

The trade-off is that the ceremony is fiddly to implement. There are a lot of moving parts and the failure modes are subtle.

## The Four Actors in the Ceremony

Before touching code, fix the cast of characters:

1. **The user** — has a device with an authenticator. Could be the same laptop (platform authenticator like Touch-Key, Windows Hello) or a separate security key like a YubiKey (roaming authenticator).
2. **The browser** — exposes the WebAuthn API to your JavaScript and brokers calls to the authenticator over CTAP1/CTAP2 or a platform-internal channel.
3. **The authenticator** — the actual key store. Holds the private key, performs the signature, and may return an attestation certificate chain attesting to its provenance.
4. **The relying party (your server)** — mints challenges, verifies responses, and stores credentials.

Every registration ceremony is a request-response pair with very specific, CBOR-and-JSON-encoded payloads. Getting the byte-level shape wrong is the most common cause of "works on my machine, fails for users" bugs.

## Anatomy of the Registration Ceremony

Here's the flow at a high level:

1. Server generates a random challenge and serializes the public-key options.
2. Browser calls `navigator.credentials.create({ publicKey })` with those options.
3. Authenticator collects a gesture (touch, fingerprint, PIN), mints a new key pair, and returns the public key + attestation signed with an attestation private key.
4. Browser hands back a `PublicKeyCredential` object to your JS.
5. Server verifies the attestation, persists the credential, and associates it with the user.

Three of these steps live in your codebase; the other two are vendor magic. Let's go through each.

### Step 1: Server Mints the Challenge

The challenge is a server-generated, single-use, cryptographically random byte string. It serves two purposes: it prevents replay, and it lets the server bind a response to the session that initiated the call.

```python
import secrets
import base64

challenge = base64url_encode(secrets.token_bytes(32))
```

A common bug: forgetting that the challenge travels as URL-safe base64 without padding. WebAuthn uses [base64url encoding](https://www.w3.org/TR/webauthn-2/#base64url-encoding) — no `+`, no `/`, no `=` padding. Your decoder on the response side must match. Off-by-one base64 errors here manifest as `TypeError` in the browser and mysterious decode failures in Python.

The other thing you mint alongside the challenge is the user handle. This is an opaque server-side identifier for the account — not the username, not the email, but a stable internal ID. It's how the browser knows what to display to the user when there are multiple credentials.

### Step 2: PublicKeyCredentialCreationOptions

Your server hands the browser something shaped like this (decoded from `attestationOptions`):

```json
{
  "rp": {
    "id": "auth.example.com",
    "name": "Example Auth"
  },
  "user": {
    "id": "dGhpc19pc19hX3VzZXJfaWQ",
    "name": "[email protected]",
    "displayName": "Alice Example"
  },
  "challenge": "Y2hhbGxlbmdlX2J5dGVz",
  "pubKeyCredParams": [
    { "type": "public-key", "alg": -7 },
    { "alg": -257, "type": "public-key" }
  ],
  "excludeCredentials": [],
  "authenticatorSelection": {
    "residentKey": "preferred",
    "userVerification": "preferred"
  },
  "attestation": "none",
  "timeout": 60000
}
```

A few non-obvious points worth highlighting:

- **`rp.id`** — must be a registrable domain suffix of (or equal to) your origin. If your login page is on `auth.example.com` but your API is on `api.example.com`, set `rp.id` to `example.com` so both can authenticate against the same credential. Get this wrong and users will see "This passkey doesn't work on this site."
- **`pubKeyCredParams`** — your preference list of signature algorithms. `-7` is ES256 (ECDSA P-256), `-257` is RS256. Put your preferred one first; the authenticator picks from the list.
- **`excludeCredentials`** — pass in the credential IDs the user has already registered, so the browser can prompt "You already have a passkey for this site." This prevents the same account from accumulating duplicate credentials.
- **`attestation`** — set to `"none"` unless you specifically need to know the authenticator model (e.g., you're an enterprise with a hardware-key allowlist). Attestation is privacy-sensitive: it tells the RP what kind of device the user owns.

### Step 3: The Browser Calls the Authenticator

Your JS is the thin shim:

```js
const credential = await navigator.credentials.create({
  publicKey: attestationOptions
});

const response = {
  id: credential.id,
  rawId: arrayBufferToBase64url(credential.rawId),
  type: credential.type,
  clientDataJSON: arrayBufferToBase64url(credential.response.clientDataJSON),
  attestationObject: arrayBufferToBase64url(credential.response.attestationObject)
};
await fetch('/webauthn/register/finish', {
  method: 'POST',
  body: JSON.stringify(response)
});
```

That `attestationObject` is a CBOR-encoded structure containing the attested credential data, the attestation statement, and (depending on format) an X.509 chain proving the attestation key came from a real FIDO device. Parsing it is where you'll spend most of your implementation effort on the server.

### Step 4: Server Verifies the Attestation

This is the part that scares engineers. It's actually a fixed checklist:

1. Decode `clientDataJSON` from base64url. Verify that:
   - `type` is `"webauthn.create"`.
   - `challenge` matches what you sent (base64url-decoded comparison, constant-time).
   - `origin` matches your expected origin. Pin this list explicitly — don't trust `request.host`.
   - `crossOrigin` is `false` (set by the browser when the call was same-origin).
2. Parse `attestationObject` as CBOR. Inside you'll find `fmt` (the attestation format), `attStmt`, and `authData`.
4. Parse `authData` to extract the **relying party ID hash** (first 32 bytes), flags, counter, and attested credential data if the AT flag is set. The RP ID hash must equal `SHA-256(rp.id)`. The UV flag (bit 2) tells you whether user verification was performed; if your policy requires `userVerification: required` and UV is unset, reject.
5. Verify the attestation statement for the given `fmt`. For `"none"` (which is what we asked for), this is a no-op. For `"packed"` or `"tpm"`, you walk the cert chain to a root you trust, then verify the inner signature over the concatenation of `authData || SHA-256(clientDataJSON)` using the credential public key from `authData`.
6. Persist `{ credentialId, publicKey, signCount, aaguid?, transports? }` against the user.

The most common libraries handle steps 1–5. On the Python side, [`py_webauthn`](https://github.com/donuts-are-good/py_webauthn) (and the original [`webauthn` by Duo](https://github.com/duo-labs/py_webauthn) before its archival) wrap most of this. On Node, [`@simplewebauthn/server`](https://simplewebauthn.dev/) is the standard. You almost never need to hand-roll CBOR parsing, but you should understand what the library is doing so that when it returns an error you can debug it.

## Patterns in Production

Once you've shipped the basic ceremony, you'll want to harden it. A few patterns we see in well-run deployments:

### Bind the Challenge to the Session

The challenge isn't just a nonce — it's a binding between the HTTP session that initiated the call and the response that comes back. Stash the challenge in a short-lived server-side store keyed by session ID, and delete it after one read. This stops an attacker from injecting a registration response from their own authenticator into another user's session.

### Use Server-Side Credential Records, Not Just Lookups

Most implementations store credentials as `{ id, public_key, sign_count, transports, last_used, friendly_name }`. Add `last_used` so you can prune credentials that haven't been used in 12 months. Add `friendly_name` so users can name their devices ("Alice's MacBook Pro Touch-Key"), because once you have three credentials on one account you will get support tickets about "passkey didn't work."

### Support Multiple Credentials per User

Don't try to enforce one passkey per account. Users lose devices. Users upgrade phones. Users have a YubiKey as a backup. The whole point of passkeys is that they're replaceable, so let users register as many as they want and treat any of them as sufficient for login. Track `last_used` so the UI can show recent credentials first.

### Decide Your User Verification Policy

`authenticatorSelection.userVerification` is the dial that controls the friction-vs-assurance tradeoff. `"preferred"` lets devices that don't have biometrics fall back to a PIN; `"required"` forces biometrics on every registration. For high-value accounts (banking, admin access), `"required"` is appropriate. For a comment section, `"discouraged"` is fine.

### Plan for the Attestation Footgun

Attestation responses can identify the model of authenticator. If you log them or store them, you may be in scope for GDPR depending on jurisdiction. Most RPs request `"none"` attestation and never store AAGUIDs. If you do need attestation (e.g., to enforce a YubiKey-only policy for admins), document the privacy choice and consider not storing it after verification.

## Common Failure Modes

Some things to anticipate before your first support ticket:

- **Challenge mismatch.** Often a base64url vs base64 mismatch, or the client decoded once and the server compared without re-encoding. Always store the raw bytes; compare byte arrays.
- **RP ID mismatch.** Login page moved to a subdomain without updating the RP ID. Pick the broadest eTLD+1 you control and pin it.
- **HTTPS required.** WebAuthn requires a secure context. The one exception is `localhost`, which browsers allow for development. Don't be surprised when your dev environment works on macOS but breaks on a Linux VM behind a private IP.
- **Cross-device flows.** QR-code login from a phone to a desktop browser uses hybrid transport (CTAP2.1). Make sure your `transports` field in the stored credential reflects what the authenticator actually advertised, otherwise the browser won't offer hybrid.
- **Sign counter rollback.** The signature counter is a tamper detector. If you see it go backwards, treat the credential as compromised and notify the user. This is the FIDO spec's defense against authenticator cloning.

## Architectural Choices: Where Passkeys Fit

In a typical production identity stack, passkeys don't replace everything — they replace one factor. The most common deployment is **passkey as first factor, with email magic-link or TOTP as fallback**. Users on modern devices get the friction-free experience; users on legacy devices get a fallback that still beats passwords.

A second common pattern is **passkey + step-up**. Initial login with a passkey; sensitive operations (changing email, viewing API tokens) require a fresh `userVerification: required` assertion. This is the FIDO equivalent of "re-enter your password to confirm."

Both of these are much easier to retrofit if your auth layer already supports multiple credential types per user — which is itself a reason not to bolt WebAuthn onto a system that assumes one password hash per account.

## Key Takeaways

- The registration ceremony is a four-actor handshake: user, browser, authenticator, server. Your server is responsible for challenge generation, response verification, and credential storage.
- The challenge must be cryptographically random, single-use, and base64url-encoded without padding. Anything else will break the round-trip.
- Set `rp.id` to the broadest registrable suffix you control, and verify `SHA-256(rp.id)` against the first 32 bytes of `authData` on every registration.
- Use `attestation: "none"` unless you have a concrete business need for hardware provenance; the privacy cost is real.
- Treat credentials as replaceable, allow multiple per user, and use a library to do the CBOR parsing — but understand what the library is verifying so you can debug when it returns a `verification_error`.

## Further Reading

- [W3C WebAuthn Level 3 specification](https://fidoalliance.org/specs/webauthn-spec-v3.0-ps-20241127.html) — the normative document, authoritative on the wire format.
- [MDN Web Docs: Web Authentication API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Authentication_API) — the most useful browser-side guide and the best explanation of `PublicKeyCredentialCreationOptions`.
- [Google Identity: Sign in with a passkey](https://developers.google.com/identity/passkeys) — practical guide with full code samples for web and Android.
- [`@simplewebauthn/server` documentation](https://simplewebauthn.dev/) — the de facto Node.js implementation, with clear examples of every ceremony step.
- [FIDO Alliance: How FIDO Works](https://fidoalliance.org/how-fido-works/) — the protocol-level explainer if you want to understand CTAP1 vs CTAP2 and the role of the Authenticator.