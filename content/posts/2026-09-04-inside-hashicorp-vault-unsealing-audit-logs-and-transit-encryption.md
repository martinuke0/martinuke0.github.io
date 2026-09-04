---
title: "Inside HashiCorp Vault: Unsealing, Audit Logs, and Transit Encryption"
date: "2026-09-04T05:00:42.995"
draft: false
tags: ["vault", "hashicorp", "secrets-management", "security", "transit", "devops"]
description: "A working engineer's deep dive into HashiCorp Vault: how unsealing works, how audit logs surface real attacks, and how the transit engine encrypts data without storing it."
summary: "A practitioner's tour of three Vault primitives engineers touch daily — the Shamir-based unseal flow, the tamper-evident audit log device, and the stateless transit encryption engine — with concrete config and production patterns."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-inside-hashicorp-vault-unsealing-audit-logs-and-transit-encryption.svg"
  alt: "Abstract vault door with glowing key shards reassembling."
  caption: ""
  relative: false
---

> **TL;DR** — Vault separates the *encryption root* from the *operational state* via Shamir's Secret Sharing, which is why "unsealing" exists at all. Every request can be persisted to a tamper-evident audit device, and the transit engine lets you encrypt application data in your own datastore without Vault ever holding the ciphertext or plaintext. Together, these three primitives turn Vault into a control plane for secrets rather than a glorified password file.

If you've deployed it once, you've had the moment: you `vault operator init`, you get five key shards and an initial root token, and your stomach drops because you realize that one of those shards, combined with the other four, *is* the master key to your entire secrets estate. Everything that follows — unsealing, audit logging, transit encryption — exists to make that power usable without making it catastrophic. This post walks through how those three pieces actually work under the hood, with the knobs engineers care about.

## Why Vault Looks the Way It Does

Vault is built around a single uncomfortable fact: a secrets manager that stores the keys to your kingdom has to be more secure than the kingdom itself. HashiCorp's answer is to split that responsibility into layers.

At the bottom is the storage backend — `integrated_storage` (Raft), Consul, or Postgres — which holds logical data: policies, token data, lease state, encrypted secret values. None of this is readable without the encryption key.

That key is the **root key**, derived by the **Keyring**, which wraps a **HMAC key**. The root key is the only thing that actually encrypts and decrypts the data in the storage backend, and Vault never writes the root key to disk or to the storage backend in a readable form. Instead, the root key is wrapped by one or more *unseal keys*, and those wrapped copies are what `vault operator init` prints out.

This is why "sealing" and "unsealing" exist as first-class concepts even in 2026. A sealed Vault can answer HTTP requests but returns `503 sealed` for everything that needs the underlying storage. An unsealed Vault has reconstructed the root key in memory and can read or write secrets. The seal/unseal dance is the boundary between *I have a Vault* and *my Vault can do anything*.

## Unsealing: Shamir, Auto-Unseal, and Recovery

### Classic unseal (Shamir's Secret Sharing)

When you run `vault operator init -key-shares=5 -key-threshold=3`, Vault generates a 256-bit master key and splits it into 5 shares using [Shamir's Secret Sharing](https://en.wikipedia.org/wiki/Shamir%27s_Secret_Sharing) over GF(256). Any 3 of the 5 shares reconstruct the master; 2 reveal nothing.

```bash
vault operator init \
  -key-shares=5 \
  -key-threshold=3 \
  -format=json > vault-init.json
```

That JSON has the shares, the initial root token, and the recovery keys. Treat it the way you treat a CA private key: paste it into the company password manager once, then delete the local file. Rotate the recovery keys if a share custodian leaves the team. The shares never change for the lifetime of a Vault cluster — re-initing generates a new root key but invalidates everything ever encrypted with the old one, which is a migration you want to avoid.

Unsealing with threshold shares:

```bash
vault operator unseal # paste share 1
vault operator unseal # paste share 2
vault operator unseal # paste share 3
# status returns 1: "Vault is unsealed"
```

Once unsealed, the root key lives in the Vault process memory until the process restarts or you call `vault operator seal`. A restart (or a crash) re-seals the Vault automatically — this is by design. The threat model is that a compromised host means the memory gets wiped and the unseal flow runs again.

### Auto-unseal replaces the human-in-the-loop

For most production deployments, manual unseal is replaced by **auto-unseal**, where the master key is wrapped by a cloud KMS: AWS KMS, GCP Cloud KMS, Azure Key Vault, or HSMs like PKCS#11. In this mode, `vault operator init` returns *zero* unseal keys — because unsealing becomes a call to the KMS to decrypt the wrapped master.

```hcl
seal "awskms" {
  region     = "us-east-1"
  kms_key_id = "arn:aws:kms:us-east-1:111122223333:key/abcd-1234"
}
```

The operational consequence is enormous: an unsealed Vault comes back from a restart without a human ceremony. But the security consequence is also real — anyone who can call that KMS key on behalf of your AWS account can unseal the Vault. The KMS key's IAM policy is now your unseal policy. Lock that down with [KMS key policies](https://docs.aws.amazon.com/kms/latest/developerguide/key-policies.html) that only allow the Vault EC2 instance role, plus CloudTrail for the KMS calls themselves.

### Recovery keys are not optional

Auto-unseal doesn't eliminate recovery keys. If your KMS key is deleted (it happens — see [GitHub's 2022 KMS incident](https://github.blog/2022-09-13-tales-from-the-cloud-deep-dive-into-a-kms-incident/)), recovery keys generated at init time are your last backstop. They behave like the old Shamir shares: printed once, threshold required, never regenerated automatically. Store them in a second, *separate* secret store — not the same KMS that wraps the master.

## Audit Logs: The Tamper-Evident Black Box

Once the Vault is unsealed, every authenticated request can be written to one or more audit devices. Audit logs are how you answer "who read the production DB password, and when?" after the fact. They are not optional in a regulated environment and they are genuinely useful even when you aren't regulated.

### Enabling and configuring an audit device

```bash
vault audit enable file file_path=/var/log/vault/audit.log
```

That creates a single audit device. In production, you usually want a sink that ships off-host immediately, so a process like VectorDB or Filebeat can tail it:

```hcl
audit "file" {
  path = "/var/log/vault/audit.log"
  format = "json"
  log_raw = false
}
```

`log_raw = false` is the important flag — it redacts request and response bodies so secret values don't end up in your audit trail. The audit record itself still tells you the path, the token's policies, the source IP, and the timestamp.

For high-assurance workloads, Vault supports **syslog** (over TLS) and **socket** audit devices that forward to a remote collector in near real-time. Pair this with an HSM-backed root so the audit device itself can't be silently tampered with by an attacker who has root on the Vault node.

### What an audit record actually looks like

```json
{
  "type": "request",
  "time": "2026-09-03T18:11:42.151Z",
  "auth": {
    "client_token": "hvb.EXAMPLEwJ1QYr",
    "accessor": "hmac-sha256:...",
    "policies": ["app-prod-read"],
    "metadata": {"role": "service"}
  },
  "request": {
    "operation": "read",
    "path": "database/creds/app-prod",
    "client_ip": "10.4.12.88"
  },
  "response": {"status": "success"}
}
```

Note the `hmac-sha256:` prefix on the accessor. Vault doesn't log the raw token — it logs an HMAC of it. That's how you can correlate activity without exposing the token. The `auth.accessor` is what gets included in every record and is what you grep for during an incident.

### Tamper evidence via HMAC chaining

Audit logs are not just records — they're a [hash chain](https://developer.hashicorp.com/vault/docs/audit/log). Each entry contains an HMAC of its own contents plus the HMAC of the previous entry. This means an attacker who edits or deletes a line in the middle of the audit file cannot recompute the chain without knowing the HMAC key, which lives only in Vault's memory.

You can verify the chain offline:

```bash
vault audit verify -file=/var/log/vault/audit.log
```

This command requires an unsealed Vault because the HMAC key only exists in memory. The output lists the entry index, whether it verified, and the previous hash. In an incident, you ship the audit file to the security team, they run verify, and you find out within seconds whether someone tampered with the trail.

### Patterns in production: shipping and alerting

Two patterns show up over and over:

1. **Ship immediately, not on rotate.** A local audit file is a liability. Configure a file audit device with a log shipping agent that streams to S3, GCS, or a SIEM in near-real-time. Don't rely on logrotate to push the file off-host.
2. **Alert on the absence of audit.** A silent audit device is a sign someone disabled it. Monitor the count of audit records per minute against a baseline; if it drops to zero, page someone. The `vault audit list` output should be in your config drift detection: any audit device missing from a baseline is a Sev1.

## Transit Engine: Encryption Without Custody

Most Vault secrets engines are *stateful*: you write a secret to Vault, Vault stores it encrypted, you read it back. The transit engine inverts the relationship. **You** store the ciphertext, in **your** database, and Vault only ever sees plaintext ephemerally. This is the engine that lets a Rails app store encrypted PII in Postgres without ever talking to Vault on the read.

### Enabling the engine

```bash
vault secrets enable transit
```

Create a named key:

```bash
vault write -f transit/keys/payment-data type=aes256-gcm96
```

The key never leaves Vault. You can rotate it, you can set a min-decryption-version, and you can configure convergent encryption so that the same plaintext always produces the same ciphertext — useful for exact-match lookups on encrypted fields.

### Encrypt and decrypt from your app

The data key is the application's API call:

```bash
vault write transit/encrypt/payment-data \
  plaintext=$(echo -n '4111-1111-1111-1111' | base64)
# => ciphertext="vault:v1:abc123..."
```

The application base64-encodes the plaintext and passes it in; Vault returns a ciphertext blob that includes the key version (`v1`), so you can decrypt with the same version or migrate to a newer one:

```bash
vault write transit/decrypt/payment-data \
  ciphertext="vault:v1:abc123..."
# => plaintext="NDExMS0xMTExLTExMTEtMTExMQ=="
```

This looks like a lot of plumbing, but the [Vault client libraries](https://developer.hashicorp.com/vault/docs/secrets/transit) wrap it cleanly:

```python
import hvac, base64

client = hvac.Client(url="https://vault.internal:8200", token=app_token)
ct = client.secrets.transit.encrypt_data(
    name="payment-data",
    plaintext=base64.b64encode(b"4111-1111-1111-1111").decode(),
)
# store ct["data"]["ciphertext"] in Postgres
```

### Key rotation without downtime

```bash
vault write transit/keys/payment-data/rotate
```

Old ciphertexts decrypt with the new key because the key metadata stores every wrapped version. To force *new* encryption to use `v2` while still decrypting `v1`:

```hcl
path "transit/encrypt/payment-data" {
  capabilities = ["update"]
  allowed_parameters = {}
}
```

```bash
vault write transit/keys/payment-data/config \
  min_decryption_version=1 min_encryption_version=2
```

Now `vault:v1:...` ciphertexts still decrypt (because `min_decryption_version=1`), but new encryptions use `v2`. After you've re-encrypted the whole dataset, you can bump `min_decryption_version=2` and the old version is effectively retired. The `vault:vN:` prefix on every ciphertext is the rotation metadata baked into the data — your app doesn't need a separate migration table.

### Envelope encryption for large payloads

For payloads larger than the transit engine's per-request limit (~64 KB by default), use **envelope encryption**. The application calls a wrapping endpoint that returns a *data key* encrypted under the named key:

```bash
vault write transit/wrapping_key/wrap \
  plaintext=$(head -c 65536 /dev/urandom | base64)
# => ciphertext="vault:v1:..."; plaintext="<base64 data key>"
```

The app decrypts the data key with `transit/decrypt`, uses it locally to encrypt the blob with AES-GCM, and stores both the encrypted blob and the wrapped data key. To decrypt, the app unwraps the data key again. The performance benefit is that you make one Vault call per blob, not per block. The security benefit is that the actual data key is only in memory during the encryption itself.

## Architecture: Putting the Three Together

A common production pattern in 2026 looks like this:

- **Vault cluster**: 3 or 5 nodes, Raft integrated storage, AWS KMS auto-unseal, deployed in a private subnet.
- **Audit devices**: one file device per node, tailed by VectorDB and forwarded to a separate AWS account's S3 bucket with object lock enabled. Alert on missing audit records.
- **App tier**: each service has a dedicated token with a policy granting transit/encrypt and transit/decrypt on its own key. Tokens are short-lived and renewed via the [Kubernetes auth method](https://developer.hashicorp.com/vault/docs/auth/kubernetes).
- **Database tier**: dynamic credentials via the database secrets engine, leased for 1 hour, revoked automatically.

The unseal story stays out of the operational loop: KMS unwraps the master on restart, recovery keys sit in an offline backup. The audit story stays out of the application loop: a separate process ships logs to a separate account. The transit story stays out of the storage loop: ciphertext lives in your Postgres, key custody lives in Vault.

That separation is the actual product. Vault isn't a secret *store* in the transit sense — it's a key custody service that produces short-lived credentials, ephemeral data keys, and tamper-evident receipts for everything it did.

## Key Takeaways

- **Unseal exists because the root key is the security boundary.** Auto-unseal moves that boundary to a cloud KMS; recovery keys are the backstop, not the primary.
- **Audit logs are a chain, not a stream.** Verify them offline; ship them off-host immediately; alert on their absence, not just their presence.
- **Transit engine lets you encrypt without custody.** The `vault:vN:` prefix is rotation metadata baked into ciphertext, which is why re-keying is a configuration change rather than a migration.
- **Hash the accessor, not the token.** Use `hmac-sha256:...` accessors in your SIEM queries; the raw token never leaves Vault.
- **Envelope encryption is the production path for anything bigger than a config value.** One Vault call per blob, not per byte.

## Further Reading

- [Vault Concepts: Seal/Unseal — HashiCorp Developer](https://developer.hashicorp.com/vault/docs/concepts/seal)
- [Shamir's Secret Sharing — Wikipedia](https://en.wikipedia.org/wiki/Shamir%27s_Secret_Sharing)
- [Vault Audit Devices — HashiCorp Developer](https://developer.hashicorp.com/vault/docs/audit)
- [Vault Transit Secrets Engine — HashiCorp Developer](https://developer.hashicorp.com/vault/docs/secrets/transit)
- [AWS KMS Key Policies — AWS Documentation](https://docs.aws.amazon.com/kms/latest/developerguide/key-policies.html)
- [Vault on Kubernetes Auth Method — HashiCorp Developer](https://developer.hashicorp.com/vault/docs/auth/kubernetes)