---
title: "Implementing End-to-End Encrypted Push Notifications with Signal and MLS"
date: "2026-09-06T12:00:29.685"
draft: false
tags: ["messaging-security", "signal-protocol", "mls", "push-notifications", "applied-cryptography", "distributed-systems"]
description: "How to design and ship end-to-end encrypted push notifications using the Signal Protocol and the IETF Messaging Layer Security standard, with concrete architecture and code."
summary: "A practical guide to delivering push notifications that the server cannot read, covering Signal's Double Ratchet, MLS group state, APNs/FCM payload constraints, and the tradeoffs you'll hit in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-implementing-end-to-end-encrypted-push-notifications-with-signal-and-mls.svg"
  alt: "Abstract diagram of encrypted message envelopes flowing from a sender through a notification gateway to multiple recipient devices."
  caption: ""
  relative: false
---

> **TL;DR** — Push notifications are an underappreciated privacy hole: the gateway, OS, and cloud messaging fabric all see the plaintext. You can close that hole by treating the push payload as just another Signal Protocol or MLS message, sealing it on the sender side and only delivering ciphertext through APNs or FCM. The result is a notification pipeline where the server is a blind courier, but you pay for it in payload size limits, key management, and silent-push complexity.

## Why Push Notifications Are a Privacy Problem

Most "end-to-end encrypted" messengers quietly break their promise the moment a notification fires. On iOS, APNs requires a visible alert payload; on Android, FCM hands its `data` payload to the system and any installed app with notification access. Either way, the notification body — the most context-revealing part of any message — ends up in a log file somewhere you do not control.

The fix is conceptually simple: never let the gateway see plaintext. Treat push as a transport, the same way you treat a TLS connection. The sender encrypts a small "wake-up" envelope to the recipient's *notification key*, the server blindly forwards it, and the recipient's device decrypts and renders the alert locally. This is the model Signal adopted in 2017 with [Sealed Sender](https://signal.org/blog/sealed-sender/) and later refined for notifications, and it is the model the IETF's MLS working group is standardizing for group chats in [RFC 9420](https://www.rfc-editor.org/rfc/rfc9420).

The hard parts are not cryptographic. They are the boring ones: APNs' 4 KB payload ceiling, FCM's two message types, device key lifecycle, and the fact that you now have to route a notification to *one of N* devices when the user has four.

## The Cryptographic Primitives You'll Actually Use

Before touching APNs, decide which protocol family you are standardizing on.

**Signal Protocol (premessage/Sealed Sender style).** The double ratchet gives you forward secrecy and post-compromise security per conversation. For a notification, you typically don't run a full ratchet round-trip — you derive a short-lived *notification key* from the long-term identity key plus a per-message ephemeral key. The recipient's device holds the corresponding private half and decrypts locally. Signal's open-source [libsignal](https://github.com/signalapp/libsignal) repository has the reference implementation.

**MLS (Messaging Layer Security, RFC 9420).** For groups, MLS is now the obvious choice. Instead of O(n) pairwise sessions, you get a single ratcheted tree key. A notification for a group of 500 is encrypted once on the sender side, and each member's device derives its own path in the tree. [RFC 9420 §5](https://www.rfc-editor.org/rfc/rfc9420) defines the tree, and the [MLS Architecture](https://www.rfc-editor.org/rfc/rfc9590.html) document (RFC 9590) covers the operational concerns. Reference libraries include [openmls](https://github.com/openmls/openmls) in Rust and a [Go implementation](https://github.com/mlswg/mls-implementations) tracked by the working group.

**HPKE (RFC 9180).** Both Signal and MLS use Hybrid Public Key Encryption under the hood. You will rarely call HPKE directly, but when you design a "sealed envelope" wrapper for a push payload — for example, a key-update beacon that is itself an MLS message — HPKE is the primitive you reach for. The Cloudflare blog has a [good primer](https://blog.cloudflare.com/relating-the-mls-and-signal-protocols/) on how Signal and MLS relate.

## Architecture: The Blind Courier Pattern

The end-to-end architecture for encrypted push looks like this:

1. **Sender device** composes the notification body and a sender metadata block (sender name, conversation title, message preview).
2. **Sender client** seals both into a single ciphertext using either the recipient's current MLS epoch secret or a derived Signal notification key.
3. **Sender client** sends a small JSON envelope to the gateway: `{ "recipient": user_id, "apns_token": "...", "fcm_token": "...", "ciphertext": "<base64>" }`. Optionally a per-message `tag` for the client to deduplicate.
4. **Gateway** looks up the active device for `user_id`, looks up the matching push token, and dispatches the ciphertext to either APNs or FCM. It learns nothing about the contents.
5. **Recipient OS** receives the push, passes the payload to the messaging app, which decrypts and renders the alert.

The crucial design choice is **where the plaintext is composed**. If the gateway can fill in the "title" or "body" field, you have already lost. Both APNs and FCM support a `mutable-content` / `content-available` flag that tells the OS to hand the raw payload to the app silently so it can decrypt before displaying. iOS also has the older `alert` field, which the OS will display directly — you simply must not put plaintext there.

### Payload shape in practice

A typical encrypted APNs payload looks like this. The gateway only ever sees the encrypted blob:

```json
{
  "aps": {
    "mutable-content": 1,
    "sound": "default"
  },
  "e2ee": {
    "v": 1,
    "kid": "mls-epoch-7421-leaf-3",
    "ct": "BASE64-CIPHERTEXT",
    "ad": "BASE64-ASSOCIATED-DATA"
  }
}
```

The `aps.alert` field is deliberately absent. iOS will still post a generic "You have a new message" notification unless the app is in the foreground, in which case the app handles everything itself. Some apps — Signal included — suppress the default banner and only render after local decryption; that requires the `content-available` push strategy plus a `Background App Refresh` entitlement on iOS, which Apple has historically granted sparingly.

## Patterns in Production

### 1. Per-device notification subkeys

The recipient's long-term identity key should not decrypt notifications directly. Instead, derive a *notification subkey* from `(identity_key, device_id, epoch)` using a KDF such as HKDF. Rotate the subkey on MLS epoch changes and on explicit "this device was compromised" events. This way, a stolen push token (which is a real attack — see [this Google Project Zero report](https://bugs.chromium.org/p/project-zero/issues/list?q=push) on token abuse) does not give the attacker access to historical message previews if you rotate aggressively.

### 2. Sealed-sender metadata for the alert

The user still wants to see "Alice: See you at 6" in their lock screen. That metadata is part of the plaintext you encrypt, not something the server knows. The sender's client packages `{ sender_name, conversation_title, body_preview, avatar_url_blob_id }` and seals it together. The app then renders the notification locally. Yes, you can also have the *recipient's* device fetch an avatar from a CDN — the CDN does not learn who is messaging whom, only that *someone* requested a particular blob.

### 3. Multi-device fanout

A user with a phone, a tablet, and a laptop has three devices, each with its own MLS leaf in the group tree. For a 1:1 conversation, the sender encrypts once per device using each leaf's path secret. For a group, MLS does this for you: a single ciphertext reaches all members of the current epoch, and each device derives its own key. The push gateway still needs to know *which APNs/FCM token to wake* for a given ciphertext. The convention is to send one push per online device, with a tiny "this device already read it" ack message that suppresses subsequent pushes for the same `tag`.

### 4. Silent push for content sync

If the goal is to update the badge count or sync new messages for when the user opens the app, you do not need to encrypt anything new — the push is just a wake-up. A 64-byte ciphertext is enough: the device receives the silent push, opens a TLS connection to your messaging service, and pulls the actual messages over an already-encrypted channel. This pattern is heavily used by WhatsApp, as described in their [encryption whitepaper](https://www.whatsapp.com/security/WhatsApp-Security-Whitepaper.pdf), and it sidesteps the APNs payload size limit entirely.

### 5. Handling FCM's two message types

FCM distinguishes between `notification` messages — which the system displays automatically, with no app involvement — and `data` messages, which the app handles. The first type is incompatible with end-to-end encryption because FCM itself sees the title and body. You must use `data` messages exclusively and rely on the app to render. There is no way around this; the official [FCM message types docs](https://firebase.google.com/docs/cloud-messaging/concept-options) are explicit.

## Pitfalls You Will Hit

**Payload size.** APNs caps regular pushes at 4 KB and VoIP pushes at 5 KB. An MLS ciphertext for a small group fits easily; for a 500-person group with a rich notification body, you can blow past it. The mitigation is the silent-push pattern: send a tiny wake-up and let the app pull the rest. If you must inline, drop the body preview and only seal the sender name plus a 16-byte tag.

**Push token churn.** iOS rotates APNs tokens when the user restores from backup, and Android does the same on FCM token refresh. Your gateway needs a reliable mapping from `user_id` to current tokens, and the messaging client must publish new tokens eagerly. A stale token in your database means dropped notifications that look like delivery failures — a debugging nightmare.

**Key transparency.** How does a device know the notification subkey it just received is really from the claimed sender, and not a MITM using a key it injected last week? This is the [CONIKS](https://www.usenix.org/system/files/conference/usenixsecurity15/usenixsecurity15-paper-melara.pdf)-style problem, and Signal's [key transparency design](https://signal.org/blog/key-transparency/) is the canonical answer. For a smaller deployment you can defer this; for anything user-trusted, you cannot.

**Compliance and abuse.** Encryption plus push is great for users, and terrible for law enforcement. If you operate in a regulated market, you need a documented key-escrow story for the notification subkeys — at minimum, a court-order workflow that lets a compliance officer with dual control reconstruct the plaintext of a specific notification. This is the same problem every E2EE messenger has, and there is no clean answer.

**Test coverage.** You will need fuzzing against your MLS or Signal implementation, plus replay-attack tests on the push layer. The [go-mls](https://github.com/mlswg/mls-implementations) project keeps a corpus of test vectors; for Signal, libsignal ships an `auditor` and a fuzz harness in CI.

## Code Sketch: Sealing a Notification with MLS

This is pseudocode using the openmls-style API. It is not runnable as-is — refer to the [openmls documentation](https://openmls.tech/book/) for current API calls — but it shows the structure:

```rust
// 1. Sender looks up the current MLS group state for the conversation.
let group = mls_group_for(conversation_id)?;

// 2. Compose the notification plaintext locally.
let plaintext = serde_json::to_vec(&json!({
    "sender": "Alice",
    "title": "Project Athena",
    "preview": "see you at 6",
    "msg_id": "01HXX...",
}))?;

// 3. Encrypt to the current epoch. openmls handles fanout across leaves.
let ciphertext = group.create_application_message(&plaintext, &sender_key, &[], 0)?;

// 4. Wrap for push: only the bytes go on the wire.
let push_envelope = json!({
    "v": 1,
    "kid": format!("mls-epoch-{}-sender-{}", group.epoch(), group.sender_index()),
    "ct": base64::encode(ciphertext.bytes()),
});
client.send_to_gateway(push_envelope).await?;
```

On the receiving device:

```rust
// 1. Receive the silent/wake-up push.
let envelope: PushEnvelope = serde_json::from_slice(&payload)?;

// 2. Look up the MLS group for this conversation and epoch.
let mut group = mls_group_for_epoch(conversation_id, envelope.kid.epoch())?;

// 3. Process the message. openmls verifies the signature, advances the ratchet,
//    and returns the plaintext only if everything checks out.
let plaintext = group.process_message(&sender_credential, envelope.ct)?;

// 4. Render the local notification from the decrypted plaintext.
render_local_notification(plaintext);
```

The crucial invariant: if `group.process_message` returns an error — bad signature, stale epoch, unknown member — you do **not** show a notification. The push is silently dropped. This is the same stance Signal takes, and it is the only safe one.

## Key Takeaways

- Treat push as a transport, not a content channel. The gateway should be a blind courier that only sees ciphertext, tokens, and routing metadata.
- Use Signal Protocol for 1:1 conversations and MLS for groups. Both are production-hardened, both have reference libraries, and both give you the cryptographic properties users actually expect.
- Ratchet the notification subkey aggressively. A stolen push token should not decrypt anything older than the current epoch.
- Default to silent push + local render. The "send a tiny wake-up, let the app pull" pattern sidesteps payload size limits and gives you a single TLS-encrypted channel for actual message content.
- Do not store plaintext server-side, and do not let APNs or FCM display fields carry anything but `mutable-content: 1` and an opaque blob.
- Plan for key transparency, key escrow for legal compliance, and fuzz testing from day one — these are not optional for a privacy-credible product.

## Further Reading

- [Signal Protocol documentation and the libsignal repository](https://github.com/signalapp/libsignal)
- [RFC 9420 — The Messaging Layer Security (MLS) Protocol](https://www.rfc-editor.org/rfc/rfc9420)
- [RFC 9590 — The Messaging Layer Security (MLS) Architecture](https://www.rfc-editor.org/rfc/rfc9590.html)
- [Apple Developer — Generating a remote notification](https://developer.apple.com/documentation/usernotifications/generating-a-remote-notification)
- [Firebase Cloud Messaging — Message types](https://firebase.google.com/docs/cloud-messaging/concept-options)
- [Signal blog — Key Transparency](https://signal.org/blog/key-transparency/)