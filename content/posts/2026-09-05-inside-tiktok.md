---
title: "Inside TikTok's HarnessDev: How They Made Scaffolding for Microservices Scale to 6,000+ Services"
date: "2026-09-05T18:45:00.042"
draft: false
tags: ["tiktok", "microservices", "platform-engineering", "developer-experience", "code-generation", "monorepo"]
description: "A deep dive into TikTok's HarnessDev paper: a service-template engine that powers 6,000+ microservices with policy, observability, and golden paths baked in."
summary: "TikTok's HarnessDev turns microservice scaffolding into a versioned, policy-aware platform. Here's what it does, why it matters, and what platform teams can borrow from it."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-inside-tiktok.svg"
  alt: "Abstract diagram of a service scaffolding platform with multiple microservices branching from a shared template repository."
  caption: ""
  relative: false
---

> **TL;DR** — HarnessDev is TikTok's internal framework for scaffolding new microservices from a curated, versioned set of templates that bake in observability, security policy, and "golden path" defaults. It has been used to create more than 6,000 services across dozens of stacks, and the recently published paper shows how it balances developer autonomy with platform guardrails by treating templates as products.

## Why service scaffolding matters at TikTok scale

When an engineering org is small, "create a new microservice" is a Slack message, a copy-pasted README, and an afternoon someone loses. When that org is TikTok — somewhere north of 6,000 production microservices, with dozens of stacks (Go, Java, Python, Node, Rust, plus several internal DSLs) — the cost of inconsistency compounds. Every service that ships without tracing, without a sane retry policy, without a tested CI workflow, becomes a small piece of technical debt that platform and SRE teams will pay interest on for years.

The recently published paper on [HarnessDev](https://arxiv.org/abs/2504.17890) describes how TikTok responded to that compounding cost. Rather than treat scaffolding as documentation, they treated it as a *product*: a versioned, policy-aware code generator with its own release train, its own compatibility matrix, and its own internal users (the application developers who `harness new` to start a service).

The framing matters. A template isn't a wiki page; it's a compiler. And like any compiler, it needs to be maintainable, testable, and able to evolve without breaking the downstream services that depend on it.

## What HarnessDev actually is

At its core, HarnessDev is a CLI plus a templating pipeline. A typical invocation looks roughly like:

```bash
harness new service payments-settlement \
  --language go \
  --runtime grpc \
  --tier critical \
  --region global
```

The CLI talks to a control plane that resolves three things:

1. **Template set.** Which curated template (or set of templates) applies to this stack? A `go-grpc` service in 2026 is not the same animal as a `go-grpc` service in 2023.
2. **Policy bundle.** What does this service tier require? A `critical` tier might mandate mTLS, dual-region active-active, on-call rotation, and a chaos test gate in CI. A `tier-3` internal tool needs none of that.
3. **Service metadata.** What's the owning team, what's the on-call channel, what compliance labels apply (PCI, PII, GDPR regions), and which deployment target (Kubernetes, Edge, internal-only).

The output isn't just a directory of files. It's a generated repository with a generated `harness.yaml` manifest that records every decision the scaffolder made. That manifest is later used by deployment, observability, and cost-allocation tooling to know what this service *is*.

### The anatomy of a template

Each template is a directory of files annotated with a templating language. Under the hood, HarnessDev uses a layered model that the paper calls *template composition*: a base template per language, plus overlays per runtime, per tier, per region.

```
templates/
├── go/                      # base Go service
│   ├── Dockerfile.tmpl
│   ├── cmd/main.go.tmpl
│   └── internal/server/server.go.tmpl
├── go/overlays/grpc/        # adds gRPC server bootstrap
├── go/overlays/tier-critical/   # adds mTLS, dual-region probes
└── go/overlays/region-cn/   # adds China-region data residency hooks
```

When a developer requests a `go`, `grpc`, `critical`, `global` service, the generator layers these directories in order, with later layers able to override files from earlier ones. This is the same compositional idea behind Kubernetes' patch semantics or Helm's `values.yaml` precedence — a small, well-understood mechanism scaled across thousands of services.

## Architecture of the platform

The paper is unusually explicit about the system architecture, which is one of its more useful contributions for other platform teams. There are four moving parts:

### 1. The template registry

A versioned store, internally called the **Template Registry**, holds every published version of every template. Each version is content-addressed and signed. Releases follow a modified semver: a *minor* bump means "new defaults are available, but your generated service still builds"; a *major* bump means "behavior changed — your service needs to be regenerated and possibly edited."

This is a familiar pattern from package ecosystems like npm or cargo, and it's deliberate. Treating templates as packages lets platform teams ship improvements asynchronously to how developers *adopt* them.

### 2. The policy engine

The policy engine is a separate service that takes the requested service metadata and returns a **policy bundle**: the set of requirements this specific service must satisfy. The paper is clear that policies are *data*, not code. A `critical-tier-policy` looks something like:

```yaml
apiVersion: harness.policy/v1
kind: Bundle
spec:
  requires:
    - name: mtls
      level: strict
    - name: tracing
      sampler: tail-based
      exportTo: ["jaeger", "otel-collector"]
    - name: chaos-test
      gate: pre-merge
      tool: chaosblade
    - name: oncall-rotation
      rotation: pageduty
      severity: critical
```

Templates read this bundle at generation time and inject the right code, configs, and CI steps. Crucially, a *change* to the policy bundle does not require a *change* to the template — it just changes what the template emits next time.

### 3. The generator

The generator is the templating engine itself. It reads template files, evaluates expressions against a context object (the developer's answers plus the resolved policy bundle), and emits a new repository. It also writes the `harness.yaml` manifest that records exactly which template version, which policy bundle version, and which overlays were used.

That manifest is the secret sauce for everything that comes after. It's the single source of truth for "what is this service, and what rules does it live under."

### 4. The reconciler

This is where the paper's design gets interesting. Once a service has been generated and deployed, a background **reconciler** continuously compares the *running* service against its declared `harness.yaml`. If a template update ships that adds, say, a new required metric, the reconciler flags the service as `drift: minor` and opens a PR. If a policy change makes a feature *mandatory* (a major bump), the service is flagged `drift: major` and routed to its owning team.

This is the same mental model as Kubernetes controllers, GitOps, and tools like [Crossplane](https://www.crossplane.io/) — declare the desired state, reconcile continuously, surface drift rather than auto-mutate it. The paper makes a strong case that this declarative-loop pattern isn't just for infrastructure; it's how you keep 6,000 services close enough to current best practice without hiring an army of platform engineers to maintain them by hand.

## Patterns in production

A few patterns from the paper are worth pulling out because they transfer cleanly to smaller orgs.

### Templates as products, not documentation

The most quotable line from the paper is roughly: *"a template without an owner is a bug."* Every published template has a designated owner team, a public roadmap, and a usage dashboard. The platform team treats template adoption as a growth metric, and they publish internal scorecards. This is the same playbook that successful open-source projects use, applied to internal infrastructure.

The lesson: if you want people to use your scaffolding, give it a name, a release cadence, and a person to email when it's broken.

### Decoupling defaults from policy

Many internal platforms fail because they entangle *opinion* with *requirement*. "We require you to use slog for logging" and "we suggest you use slog for logging" look identical in code, but they're completely different statements. HarnessDev keeps them separate. The template emits a default logger; the policy engine emits the requirement that *something* structured must be used. They can evolve independently.

### Generating the manifest, not just the code

A surprising amount of value comes from the `harness.yaml` manifest, not the generated Go code. The manifest is what lets other systems (deployment, observability, FinOps, compliance) reason about services *without parsing their code*. This is the same insight behind [Backstage's catalog model](https://backstage.io/docs/features/software-catalog/software-catalog-desc), and it's worth copying even if you're not building a scaffolder: a small, generated, declarative record of "what is this thing" pays for itself very quickly.

### Drift surfacing, not auto-remediation

When templates update, HarnessDev does *not* rewrite the developer's repository. It opens one. The paper is explicit that auto-merging generated code is a fast path to broken services and lost trust. Drift as a PR, drift as a dashboard, drift as a metric that on-call leads can see — but never drift as a silent overwrite.

## How it compares to similar systems

HarnessDev is not the first internal scaffolding system — far from it. The interesting question is what it does differently.

| System | Originating org | Primary difference from HarnessDev |
|---|---|---|
| [Backstage Software Templates](https://backstage.io/docs/features/software-templates/) | Spotify | Open-source, plugin-based, less prescriptive about policy bundling |
| [Yeoman](https://yeoman.io/) | Google/open-source | Generators, not declarative state — no built-in reconciler |
| [Cookiecutter](https://cookiecutter.readthedocs.io/) | Open-source community | Single-shot generation, no versioning or drift detection |
| [Nx generators](https://nx.dev/generators) | Nrwl | Monorepo-first, less focus on multi-stack heterogeneity |
| HarnessDev | TikTok | Treats templates as versioned products with policy bundles and a reconciler loop |

The combination of *versioned templates* + *policy-as-data* + *declarative manifest* + *continuous reconciliation* is what sets it apart. Most competitors offer the first two. Few offer the third, and almost none offer the fourth.

## What platform teams should steal

If you're running a platform team and the org is anywhere past "we have a wiki page about service creation," the paper is essentially a checklist of what to build next, in what order:

- **Start with a manifest.** Even if you generate nothing else, generate a `service.yaml` that records owner, tier, stack, and compliance labels. It will earn its keep within a quarter.
- **Layer templates by axis.** Don't try to make one template per stack × runtime × tier × region. Compose overlays instead. The combinatorial space is smaller than you think.
- **Make policy data, not code.** A YAML bundle you can version in Git will be easier to evolve than a Python script that codifies the same rules.
- **Add a reconciler early.** You don't need a control plane; a weekly CI job that diffs each service's `harness.yaml` against the latest policy version and opens a tracking issue is enough to start.
- **Treat your scaffolder as a product.** Name it. Give it a release cadence. Publish adoption metrics. The single biggest predictor of whether a platform team succeeds or becomes a bottleneck is whether their tools feel like products or like mandates.

## Open questions from the paper

The paper is candid about what doesn't work yet. A few honest limitations worth noting:

- **Multi-stack services remain hard.** A service that's 70% Go and 30% Python (think: a gRPC front end with a Python ML model behind it) doesn't fit the layered-template model cleanly. The team is reportedly exploring a "polyglot composition" model but hasn't shipped it.
- **Policy conflicts are still manual.** When two policies disagree — say, "log all PII" vs. "redact all PII" — the engine raises a conflict and a human resolves it. There's no automated arbitration, and the paper admits this is the right call given how rare but high-stakes the conflicts are.
- **Cost attribution is incomplete.** The `harness.yaml` includes enough metadata to allocate compute cost back to teams, but the team has not yet integrated it with their full FinOps pipeline.

These are honest limitations, and they're the kind of things other orgs should expect to hit too. The paper's willingness to name them is part of why it's worth reading.

## Key Takeaways

- **HarnessDev is a template engine plus a policy engine plus a reconciler.** It treats service scaffolding as a versioned product, not a wiki page.
- **The `harness.yaml` manifest is the keystone.** It's what lets every other system (deployment, observability, FinOps, compliance) reason about services without parsing code.
- **Policy is data, not code.** A YAML bundle per service tier is more maintainable than hardcoded rules baked into templates.
- **Drift is surfaced, not auto-fixed.** The reconciler opens PRs; humans approve them. This preserves trust and keeps the system debuggable.
- **Templates are layered.** Base templates + overlays per axis is a much simpler model than one-template-per-combination, and it scales.
- **The paper's biggest lesson is cultural, not technical.** Successful platform engineering looks less like shipping software and more like running a product with owners, roadmaps, and users.

## Further Reading

- [HarnessDev paper on arXiv](https://arxiv.org/abs/2504.17890)
- [Backstage Software Templates (Spotify)](https://backstage.io/docs/features/software-templates/)
- [Crossplane — declarative infrastructure with a reconciler loop](https://www.crossplane.io/)
- [Nx generators — composable code generation in a monorepo](https://nx.dev/generators)
- [Cookiecutter — single-shot templating for Python projects](https://cookiecutter.readthedocs.io/)
- [Backstage Software Catalog model — why a generated manifest pays for itself](https://backstage.io/docs/features/software-catalog/software-catalog-desc)