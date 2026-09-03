---
title: "Inside WebAuthn: How Passkeys Really Work Under the Hood"
date: "2026-09-03T19:00:46.598"
draft: false
tags: ["webauthn", "passkeys", "authentication", "security", "cryptography"]
description: "A deep dive into the WebAuthn protocol, from attestation to assertion, explaining how passkeys replace passwords with public key cryptography."
summary: "WebAuthn replaces shared secrets with public key cryptography bound to a device. This post walks through the registration and authentication ceremonies, the role of authenticators and the client, and why passkeys are phishing-resistant by construction."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-inside-webauthn-how-passkeys-really-work-under-the-hood.svg"
  alt: "Stylized illustration of a public key handshake between a browser and a relying party server."
  caption: ""
  relative: false
---

> **TL;DR** — WebAuthn is a W3C standard that lets a browser or platform register a public key with a server and later prove possession of the corresponding private key during login. The server never sees the private key, the origin is cryptographically bound to the assertion, and that combination is what makes passkeys genuinely phishing-resistant rather than just "passwordless."

## Why WebAuthn Exists

Passwords are a 60-year-old hack. They are easy to phish, easy to reuse, easy to leak in breaches, and terrible at scale — every major breach since 2013 has had passwords at the center. FIDO Alliance, the W3C, and the major platform vendors spent nearly a decade designing a replacement that didn't trust the human to remember anything sensitive, and the result is the Web Authentication API, commonly called WebAuthn, with credentials that consumers know as **passkeys**.

The core idea is older than the web: a public/private keypair, generated on the user's device, where the server only ever stores the public half. When the user logs in, the server sends a random challenge, the device signs it with the private key, and the server verifies the signature. Simple in principle, but the protocol layers on top of this are what make it actually work on the open web: origin binding, attestation, resident credentials, discoverable credentials, user verification, and the awkward two-protocol split between WebAuthn and CTAP2.

This post walks the full path: from the moment a user clicks "create a passkey" through the cryptographic ceremonies, the role of the authenticator, the data the server actually stores, and the verification steps that make a valid assertion.

## The Cast: Relying Party, Client, and Authenticator

Every WebAuthn interaction involves three parties:

- **Relying Party (RP)** — your server. GitHub, your bank, your internal admin tool. It owns the user account and decides what credentials are valid.
- **Client** — the browser, the OS, or a native app's WebAuthn shim. It mediates between the RP and the authenticator, enforces the origin, and surfaces UI to the user.
- **Authenticator** — the thing that actually owns the private key and can perform user verification. Modern authenticators are usually the platform itself (iCloud Keychain, Windows Hello, Android Credential Manager, 1Password) wrapped around a TPM or Secure Enclave, but they can also be roaming hardware keys like a YubiKey.

The protocol is defined in two specs that you need to keep straight: the [WebAuthn Level 3 spec](https://www.w3.org/TR/webauthn-3/) handles the client-to-server API and the data formats, while [CTAP2](https://fidoalliance.org/specs/fido-v2.2-ps-20250714/fido-client-to-authenticator-protocol-v2.2-ps-20250714.html) defines how a roaming authenticator talks to the platform over USB, NFC, or Bluetooth. Most of the interesting work happens at the WebAuthn layer.

## The Registration Ceremony

The first half of a passkey's life is **registration**. The user clicks a "Create a passkey" button, the RP generates a challenge, the client collects a public key from the authenticator, and the RP stores it.

### Step 1: Server Issues a Challenge

The RP generates a cryptographically random byte string, stores it in a session or short-lived token, and asks the client to create a new credential. In code, this looks like the following on a Node server using SimpleWebAuthn:

```javascript
const options = {
  rp: { name: "Example Corp", id: "example.com" },
  user: {
    id: Uint8Array.from(userId, c => c.charCodeAt(0)),
    name: "alice@example.com",
    displayName: "Alice",
  },
  challenge: crypto.getRandomValues(new Uint8Array(32)),
  pubKeyCredParams: [
    { type: "public-key", alg: -7 },   // ES256
    { type: "public-key", alg: -257 }  // RS256
  ],
  authenticatorSelection: {
    residentKey: "required",
    userVerification: "preferred"
  },
  timeout: 60000
};
session.challenge = options.challenge;
```

Two things matter here. First, the `challenge` is a server-generated nonce that the client will have to echo back, proving that the resulting credential is fresh. Second, the `rp.id` field pins the credential to a specific registrable domain — `example.com` for production, not `auth.example.com` or `localhost`. That domain will be baked into the credential and verified on every future login.

### Step 2: Client Calls `navigator.credentials.create()`

The browser invokes the WebAuthn API, which hands off to the platform's authenticator. Internally, the authenticator does the following:

1. Generates an asymmetric keypair. The algorithm is one of the algorithms listed in `pubKeyCredParams` that the authenticator supports. ES256 (`-7`) is the modern default, with EdDSA (`-8`) increasingly common.
2. Creates an **attestation object** containing the public key, the credential ID, signature counters, and attestation evidence.
3. Optionally performs **user verification** — a biometric, a PIN, or a platform presence check — gated by the `userVerification` flag in the request.
4. Returns the whole thing to the browser, which hands it to JavaScript as a `PublicKeyCredential`.

The private key never leaves the authenticator. It is generated inside a Secure Enclave on iOS, inside a TPM on Windows, or inside the platform's hardware-backed keystore on Android. Roaming authenticators like YubiKeys generate it inside their own secure element.

### Step 3: Server Verifies and Stores

The browser posts the response back to your server. The server:

1. Verifies that the challenge matches the one it stored in the session.
2. Parses the attestation object. Attestations are CBOR-encoded and signed; the server extracts the public key, the credential ID, the AAGUID, and the sign count.
3. Validates the attestation signature against the manufacturer's root certificate if you care about provenance, which most apps skip.
4. Stores `credentialId`, `publicKey`, `signCount`, `transports`, and `aaguid` against the user record.

That `publicKey` is the only sensitive thing the server holds, and it is mathematically useless to an attacker without the private key.

```sql
CREATE TABLE webauthn_credentials (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES users(id),
  credential_id BYTEA NOT NULL UNIQUE,
  public_key    BYTEA NOT NULL,
  sign_count    BIGINT NOT NULL DEFAULT 0,
  aaguid        BYTEA,
  transports    TEXT[],
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at  TIMESTAMPTZ
);
```

## The Assertion Ceremony

Login is the inverse: the server challenges the client, the client asks an authenticator to sign the challenge, and the server verifies the signature against the stored public key.

```javascript
const assertion = await navigator.credentials.get({
  publicKey: {
    challenge: serverChallenge,
    rpId: "example.com",
    allowCredentials: [{
      id: credentialId,
      type: "public-key",
      transports: ["internal", "hybrid"]
    }],
    userVerification: "preferred"
  }
});
```

If the user has multiple credentials, the browser either filters by `allowCredentials` or, if the server didn't send any — making this a **discoverable credential** request — the browser shows an account chooser populated from the resident credentials on the device. That latter flow is what powers the "Sign in with a passkey" UI that replaced "Sign in with Google" on a lot of sites.

The authenticator signs a **clientDataJSON** plus an **authenticatorData** blob, increments its internal signature counter, and returns the assertion. The server reconstructs the same `authenticatorData` + `clientDataJSON` from the request, verifies the signature with the stored public key, and checks several invariants:

- The challenge matches what the server issued.
- The **RP ID hash** in `authenticatorData` matches the expected `rpId`.
- The **origin** in `clientDataJSON` matches a trusted origin for that RP ID.
- The **user present (UP)** flag is set, and **user verified (UV)** is set if you required it.
- The sign count is greater than the previously stored value, unless the credential is marked as a roaming authenticator that doesn't maintain one.

The second-to-last check is the part that defeats phishing. Because the origin is signed into the assertion, a credential registered for `example.com` cannot be replayed against `evil-example.com`, even if the user is tricked into submitting it there. The browser will refuse to issue the assertion in the first place because the calling origin does not match the RP ID the credential was bound to.

## Attestation, in Plain English

Attestation is the part of WebAuthn that confuses people, partly because the same word is used for several different things.

The **attestation object** returned at registration is a CBOR-encoded payload that contains the new credential's public key and a signature over it. The signature is produced by a key in the authenticator's **attestation key chain**, which traces back to a root certificate managed by the vendor. The AAGUID identifies which model of authenticator generated the key.

Why does this matter? In high-security environments — a bank, a defense contractor, a CI runner — you want to know whether a credential was created on a YubiKey 5, a Windows Hello TPM, or some random Android device. Attestation lets you write a policy like "only accept credentials from AAGUIDs in our approved list" and reject everything else. For a typical consumer app, attestation is mostly noise and you can ignore it.

There are three main flavors:

- **None** — the authenticator doesn't attest. Most consumer devices do this. It tells you nothing about provenance.
- **Self** — the credential's keypair signs its own attestation. It proves the keypair is real but tells you nothing about the device.
- **Basic / AttCA** — the vendor signs. This is what lets you distinguish a YubiKey from a software keychain.

The 2023-vintage **Privacy CA** flow was deprecated; modern browsers either return none, self, or direct device attestation. The [FIDO Metadata Service](https://fidoalliance.org/metadata/) is the canonical source for which AAGUIDs are real and what their attestation roots are.

## Discoverable Credentials and the "Passkey" UX

The term **passkey** is really a marketing label for a particular configuration of WebAuthn: discoverable, synced, and tied to a platform keychain. Each of those terms is doing real work.

**Discoverable credentials** (the spec calls them "resident keys") are stored on the authenticator in a way that lets the browser list them by `rpId` without the server having to send `allowCredentials`. That is what makes the platform account chooser work — when you click "Sign in," the browser can ask "do I have any passkeys for `github.com`?" and show the user a list.

**Synced** means the private key material is end-to-end encrypted between the user's devices via a vendor-controlled mechanism. iCloud Keychain syncs between Apple devices, Google Password Manager syncs between Android devices and Chrome on macOS, and 1Password and Dashlane sync across everything. The sync is what makes passkeys usable as a replacement for passwords, since users no longer have to carry a hardware token.

The trade-off is that synced passkeys are slightly weaker than non-synced ones from a security model standpoint. A compromised cloud account could, in theory, be used to add a passkey to a new device. The platforms mitigate this with device-to-device E2EE, recovery keys, and tight account recovery flows, but this is a real delta from the "you hold the only copy" model of a YubiKey. For high-assurance use cases, the [FIDO Alliance's guidance](https://fidoalliance.org/passkeys/) explicitly recommends keeping a hardware key in the loop.

## Patterns in Production

A few patterns I've seen land well in real deployments.

**Always require user verification for new device logins.** `userVerification: "required"` is the difference between "the user is present" and "the user proved who they are." A platform biometric or PIN check is what stops a thief from using an unlocked phone.

**Don't ship your own WebAuthn library if you can avoid it.** The [SimpleWebAuthn](https://simplewebauthn.dev) server library and the corresponding browser helpers handle the genuinely fiddly parts — CBOR parsing, signature verification across multiple algorithms, attestation validation — and get security updates as browsers evolve. The bug surface is real.

**Make passkey enrollment a feature, not a setup step.** Sites that show "Add a passkey for faster sign-in" on the third successful password login convert dramatically better than sites that ask at signup. The [Google Identity blog](https://security.googleblog.com/2023/05/implementing-passkey-upgrade-for.html) has published their flow and the conversion numbers; they are striking.

**Treat the sign count seriously.** If the sign count on a returned assertion is less than what you stored, treat it as a cloned-credential signal and either reject the assertion or require step-up authentication. The [Yubico developer docs](https://developers.yubico.com/WebAuthn/) walk through the counter logic in detail.

**Plan for cross-device passkeys (hybrid transport).** The "hybrid" transport, where a phone approves a login on a desktop via QR code, uses BLE to bridge the two devices and then performs a normal WebAuthn ceremony. The UX is genuinely magical and a meaningful chunk of users will hit it. Your server needs to allow the `hybrid` transport in `allowCredentials.transports`, and your CORS and CSP must permit the BLE-adjacent flows.

## What WebAuthn Doesn't Solve

WebAuthn is not a complete authentication system. The protocol answers "does this user control this credential at this origin right now?" and nothing else.

It doesn't handle account recovery. If a user loses every enrolled device and every synced backup, they're locked out. Most production deployments pair passkeys with a fallback — a recovery code, a magic link, a hardware key held in escrow, or a human-reviewed recovery process. The [Bitwarden passkey rollout post](https://bitwarden.com/blog/passkeys-faq/) is a good walkthrough of how a consumer product handled the recovery tension.

It doesn't handle device transfer or inheritance. If you die and your family wants into your bank account, a passkey-protected account is harder to access than a password-protected one. The platforms are working on it; FIDO's [Digital Identity working group](https://fidoalliance.org/working-groups/) has recovery on its roadmap, but it's not solved.

And it doesn't replace authorization. A valid passkey assertion proves the user is present, not that the user is allowed to perform a particular action. That stays your job.

## Key Takeaways

- WebAuthn replaces a shared secret with a public key, generated and stored on the user's device; the server only ever holds the public half.
- The registration ceremony produces an attestation object; the assertion ceremony produces a signed challenge. Both bind the credential to a specific RP ID and origin.
- The origin binding is what makes passkeys phishing-resistant. A credential for `example.com` cannot be used at `evil-example.com`, because the browser enforces the RP ID match before invoking the authenticator.
- Discoverable credentials and platform syncing are what turn WebAuthn from a developer API into the "passkey" UX consumers actually use.
- Attestation is optional metadata about which device created a credential; ignore it for consumer apps, enforce it for high-assurance deployments.
- Recovery, device transfer, and the "what if the user dies" problem are not solved by WebAuthn. They are product decisions you still have to make.

## Further Reading

- [Web Authentication Level 3 (W3C)](https://www.w3.org/TR/webauthn-3/)
- [FIDO Alliance Passkeys Overview](https://fidoalliance.org/passkeys/)
- [SimpleWebAuthn Documentation](https://simplewebauthn.dev)
- [Google Security Blog: Implementing Passkey Upgrade](https://security.googleblog.com/2023/05/implementing-passkey-upgrade-for.html)
- [MDN Web Docs: Web Authentication API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Authentication_API)
- [Yubico WebAuthn Developer Guide](https://developers.yubico.com/WebAuthn/)