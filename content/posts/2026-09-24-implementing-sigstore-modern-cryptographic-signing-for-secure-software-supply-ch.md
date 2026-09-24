---
title: "Implementing Sigstore: Modern Cryptographic Signing for Secure Software Supply Chains"
date: "2026-09-24T08:01:48.398"
draft: false
tags: ["sigstore", "cryptographic-signing", "software-supply-chain", "security", "devsecops", "slsa"]
description: "A practical guide to implementing Sigstore for cryptographic signing in your software supply chain. Learn how to use Cosign, Fulcio, and Rekor to sign artifacts, verify provenance, and meet SLSA requirements."
summary: "Sigstore provides a free, open-source framework for signing software artifacts with short-lived certificates. This post walks through implementing Cosign, Fulcio, and Rekor to secure your supply chain and meet SLSA compliance goals."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-24-implementing-sigstore-modern-cryptographic-signing-for-secure-software-supply-ch.svg"
  alt: "A visual representation of the Sigstack ecosystem showing Cosign, Fulcio, and Rekor components working together in a software supply chain pipeline."
  caption: ""
  relative: false
---

> **TL;DR** — Sigstore eliminates the complexity of traditional cryptographic signing by providing free, short-lived certificates and an immutable transparency log. Implementing Cosign, Fulcio, and Rekor in your CI/CD pipeline takes under an hour and dramatically raises the bar against supply chain attacks like dependency confusion and tampering.

Software supply chain attacks have surged in recent years. The SolarWinds breach, the xz-utils backdoor attempt, and countless dependency confusion incidents share a common root cause: unsigned or poorly signed artifacts that cannot be reliably attributed or verified. Sigstore addresses this by making cryptographic signing as frictionless as HTTPS.

At its core, Sigstore is not a single tool but an ecosystem. It provides a free certificate authority (Fulcio), an immutable transparency log (Rekor), and a client tool for signing and verifying artifacts (Cosign). Together, these components form a complete signing infrastructure that would traditionally cost organizations hundreds of thousands of dollars in PKI setup and maintenance.

This post walks through the architecture, implementation patterns, and practical steps to integrate Sigstore into a modern CI/CD pipeline.

## Why Traditional Signing Falls Short

Most organizations that do sign their artifacts rely on long-lived GPG keys or X.509 certificates stored in HSMs or vaults. While functional, this approach introduces several problems:

- **Key management overhead**: Rotating signing keys requires coordination across teams and can break verification pipelines if not handled carefully.
- **No transparency**: Without a public log, there is no way to prove when a signature was created or detect unauthorized signing.
- **Cost and complexity**: Running a private CA with hardware security modules is expensive and requires dedicated operations expertise.
- **Single point of failure**: A compromised signing key can sign arbitrary artifacts, and detecting that compromise is difficult without transparency logs.

Sigstore flips this model. Instead of managing your own CA, you trust a community-operated one that issues short-lived certificates tied to your identity (via OIDC). Instead of a private audit log, you write to a public, immutable transparency log that anyone can monitor.

## The Sigstore Architecture

Understanding the three core components is essential before implementation:

### Fulcio — The Certificate Authority

Fulcio is a free, open-source certificate authority that issues short-lived X.509 certificates based on OpenID Connect (OIDC) identity. When you authenticate through a supported provider (GitHub Actions, GitLab CI, Google Cloud, etc.), Fulcio issues a certificate that binds your identity to a public key.

These certificates are valid for a short duration (typically hours), which limits the blast radius of any compromise. There is no long-lived signing key to protect.

```yaml
# Example: GitHub Actions OIDC configuration for Fulcio
# The workflow assumes the standard github.com OIDC issuer
oidc_issuer: https://token.actions.githubusercontent.com
subject: https://github.com/your-org/your-repo/.github/workflows/build.yml@refs/heads/main
```

### Rekor — The Transparency Log

Rekor is an immutable, append-only transparency log that records every signature issued through the Sigstore ecosystem. Each entry contains a signed artifact descriptor and a Merkle tree proof, allowing anyone to verify that a signature existed at a specific point in time.

Rekor serves two critical functions:

1. **Non-repudiation**: Once a signature is logged, neither the signer nor the Sigstore operators can deny its existence.
2. **Monotonic sequence**: The log provides a verifiable ordering of all signatures, enabling detection of anomalous signing patterns.

You can query Rekor at [rekor.sigstore.dev](https://rekor.sigstore.dev) to inspect any logged signature.

### Cosign — The Client Tool

Cosign (now part of the Sigstore project) is the primary CLI tool for signing and verifying OCI containers, Helm charts, and other artifacts. It handles the entire workflow: generating keys, obtaining Fulcio certificates, signing artifacts, and pushing transparency log entries to Rekor.

```bash
# Sign a container image with a Fulcio certificate
cosign sign --yes oci://ghcr.io/your-org/your-image:latest

# Verify the signature and transparency log entry
cosign verify --key https://raw.githubusercontent.com/sigstore/cosign/main/pkg/cosign/testdata/pubkey.pem \
  oci://ghcr.io/your-org/your-image:latest
```

## Implementation Patterns in Production

### Pattern 1: CI/CD Pipeline Signing

The most common integration point is the CI/CD pipeline itself. In a GitHub Actions workflow, signing happens after the build and before the push to a container registry.

```yaml
name: Build and Sign
on:
  push:
    branches: [main]

jobs:
  build-and-sign:
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # Required for OIDC with Fulcio
      contents: read
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ghcr.io/your-org/your-image:latest

      - name: Install Cosign
        uses: sigstore/cosign-installer@v3

      - name: Sign the image
        run: cosign sign --yes oci://ghcr.io/your-org/your-image:latest
```

The critical detail here is `permissions: id-token: write`. This grants the workflow an OIDC token that Fulcio uses to verify identity and issue a certificate. Without this, Cosign cannot obtain a Fulcio certificate.

### Pattern 2: Keyless Signing with Policy Enforcement

Keyless signing means no keys are stored in your repository or CI environment at all. The signing identity comes entirely from the OIDC token. This is the most secure approach because there is no secret to leak.

However, keyless signing requires policy enforcement to prevent unauthorized entities from signing artifacts on your behalf. You define a policy that specifies which OIDC subjects are allowed to sign.

```bash
# Generate a policy that restricts signing to a specific workflow
cosign generate policy > policy.yaml

# Edit policy.yaml to restrict to your repository and branch
cat policy.yaml
```

```yaml
# policy.yaml — restrict signing to a specific workflow
default:
  issuers:
    - issuer: https://token.actions.githubusercontent.com
      subject: "https://github.com/your-org/your-repo/.github/workflows/release.yml@refs/heads/main"
  identities:
    - name: "https://github.com/your-org/your-repo/.github/workflows/release.yml@refs/heads/main"
```

```bash
# Apply the policy
cosign load policy policy.yaml

# Verify an artifact against the policy
cosign verify --policy policy.yaml oci://ghcr.io/your-org/your-image:latest
```

### Pattern 3: Hybrid Signing with Key Bound to CI

Some organizations prefer to retain a degree of key control while still benefiting from transparency logs. In this pattern, Cosign generates an ephemeral key pair during the CI run, signs the artifact, and the private key is never persisted.

```bash
# Generate an ephemeral key pair
cosign generate-key-pair

# The private key is stored only in the CI environment variable
# The public key is published to a known location
export COSIGN_PRIVATE_KEY="..."
export COSIGN_PUBLIC_KEY="..."

# Sign the artifact
cosign sign --key env://COSIGN_PRIVATE_KEY oci://ghcr.io/your-org/your-image:latest
```

This approach provides the transparency benefits of Rekor without fully surrendering control to the OIDC identity. The trade-off is that you must securely manage the ephemeral private key during the CI run.

## Integrating with SLSA Compliance

The Supply-chain Levels for Software Artifacts (SLSA) framework defines increasing levels of assurance for build processes. Sigstore directly supports SLSA Level 3 and above.

SLSA Level 3 requires:

1. **Hermetic builds**: The build process is isolated and reproducible.
2. **Provenance**: A signed statement describing how the artifact was built.
3. **Source integrity**: The source code is tracked in a version control system.

Sigstore's Cosign can generate SLSA provenance statements alongside container signatures. Combined with a build system like Buildkit or Bazel, you can achieve full SLSA Level 3 compliance.

```bash
# Generate SLSA provenance and sign it
cosign attest --type spdx --artifact oci://ghcr.io/your-org/your-image:latest \
  --predicate sbom.spdx.json

# Verify the provenance
cosign verify-attestation --type spdx oci://ghcr.io/your-org/your-image:latest
```

Organizations targeting SLSA Level 4 (further requiring non-falsifiable provenance) should combine Sigstore with a build system that produces reproducible outputs and publishes build logs to Rekor.

## Practical Considerations and Gotchas

### Registry Support

Not all container registries support cosign's signature storage format. The most straightforward approach is to use registries that support the [OCI Artifact Spec](https://github.com/opencontainers/image-spec/blob/main/manifest-v1-1.md), which allows storing signatures alongside images. GitHub Container Registry (GHCR), AWS ECR, and Azure Container Registry all support this.

For registries that do not support OCI artifacts, you can store signatures externally using a signature store like [Sigstore's own signature server](https://github.com/sigstore/sigstore) or a custom implementation.

### Key Rotation and Revocation

Because Fulcio issues short-lived certificates, traditional key rotation is largely unnecessary. The certificate expires naturally. However, if you need to revoke a signing identity (for example, after a team member leaves), you must update your policy and potentially rotate the OIDC configuration.

### Cost

Sigstore is free for public projects and has generous free tiers for private use. Fulcio and Rekor are operated by the Sigstore community with support from Linux Foundation hosting. You should not encounter meaningful costs unless you are operating at extreme scale.

### Offline Signing

For air-gapped environments or highly restricted networks, Sigstore supports offline signing with pre-generated certificates. You can obtain a Fulcio certificate in advance, store it securely, and use it to sign artifacts without network access. The transparency log entry can be batched and uploaded later.

```bash
# Offline signing with a pre-downloaded certificate and key
cosign sign --cert offline-cert.pem --key offline-key.pem \
  oci://ghcr.io/your-org/your-image:latest

# Upload the Rekor entry when connectivity is restored
cosign upload-attestation --rekor-url https://rekor.sigstore.dev \
  --artifact oci://ghcr.io/your-org/your-image:latest
```

## Monitoring and Auditing

Once Sigstore is in place, you need monitoring to detect anomalies. Rekor provides a public log, but you should also set up alerts for:

- **Unexpected signing events**: Monitor Rekor for signatures from your repository that were not triggered by your CI pipeline.
- **Certificate expiration**: Track when Fulcio certificates expire and ensure renewal processes are in place.
- **Policy violations**: Log all verification failures and investigate them promptly.

```bash
# Query Rekor for all entries related to your image
cosign verify --rekor-url https://rekor.sigstore.dev \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  oci://ghcr.io/your-org/your-image:latest
```

## Key Takeaways

- **Sigstore eliminates the cost and complexity of traditional PKI** by providing free, short-lived certificates through Fulcio and an immutable transparency log through Rekor.
- **Keyless signing via OIDC is the most secure pattern** because there are no secrets to manage, but it requires careful policy enforcement to prevent unauthorized signing.
- **Cosign integrates directly into CI/CD pipelines** with minimal configuration — the critical requirement is granting the `id-token: write` permission in your workflow.
- **Sigstore directly supports SLSA compliance**, enabling organizations to meet provenance and integrity requirements for regulated industries.
- **Short-lived certificates reduce blast radius** but require monitoring for unexpected signing events and policy violations.
- **Offline signing is supported** for air-gapped environments, making Sigstore viable for organizations with strict network restrictions.

## Further Reading

- [Sigstore Official Documentation](https://docs.sigstore.dev) — Comprehensive guides covering Cosign, Fulcio, Rekor, and the entire Sigstore ecosystem.
- [SLSA Framework Specification](https://slsa.dev) — The official specification for Supply-chain Levels for Software Artifacts, including requirements for each level.
- [Cosign GitHub Repository](https://github.com/sigstore/cosign) — Source code, release notes, and community-contributed examples for signing workflows.
- [Rekor Explorer](https://rekor.sigstore.dev) — Public interface for querying the Sigstore transparency log and verifying signature provenance.
- [OCI Artifact Specification](https://github.com/opencontainers/image-spec/blob/main/manifest-v1-1.md) — The OCI standard that enables storing signatures and attestations alongside container images.