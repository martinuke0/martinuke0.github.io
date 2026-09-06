---
title: "Implementing Hermetic Builds with Bazel and Buildbuddy for Reproducible CI Pipelines"
date: "2026-09-06T13:00:31.388"
draft: false
tags: ["bazel", "buildbuddy", "hermetic-builds", "ci-cd", "reproducible-builds", "supply-chain"]
description: "A practitioner's guide to building hermetic, reproducible CI pipelines with Bazel and Buildbuddy, covering rules, remote caching, and supply-chain guarantees."
summary: "How to combine Bazel's hermetic execution model with Buildbuddy's remote build cache and execution to ship faster, more reliable CI pipelines."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-implementing-hermetic-builds-with-bazel-and-buildbuddy-for-reproducible-ci-pipelines.svg"
  alt: "Diagram of a Bazel build graph with remote cache nodes."
  caption: ""
  relative: false
---

> **TL;DR** — Bazel enforces hermeticity by sandboxing every action and hashing its inputs, while Buildbuddy layers on a remote cache and execution backend that turns that hermeticity into shared, distributed speedups. Together they collapse flaky, slow CI into a reproducible pipeline where the same commit always produces the same artifacts.

## Why Hermetic Builds Matter in Modern CI

A **hermetic build** is one whose output depends only on the declared inputs — source files, toolchain, environment — and nothing else. No ambient `$PATH` that a teammate happened to install, no cached `~/.m2/repository` that differs between runners, no clock skew, no leftover files from a previous build. If you replayed the build on a clean machine in a clean room, you'd get byte-identical output.

In CI, the absence of hermeticity shows up as the worst class of bug: the *sometimes-green, sometimes-red* build. Engineers learn to retry. PRs sit in queue. Releases slip. Worse, when you ship binaries, non-determinism lets attackers slip tampered artifacts into your supply chain without breaking the build — because the build "looks fine."

Bazel was designed from day one around this problem, as documented in the [Bazel build encyclopedia](https://bazel.build/basics/hermeticity). Every action runs in a sandbox with an explicitly declared set of inputs and outputs. Buildbuddy extends that with a remote build cache and execution backend — the missing piece that turns "the build is hermetic" into "the build is hermetic *and* shared across the team."

## The Hermeticity Contract: What Bazel Guarantees

Bazel achieves hermeticity through three mechanisms working in tandem:

1. **Sandboxed actions.** Every compile, test, and genrule runs inside a sandbox with a hashed view of its declared inputs. On Linux, this is typically a user-namespaced chroot. The action sees only what its rule declares; it cannot reach the network, the home directory, or arbitrary files.
2. **Input hashing.** Each action's key is a SHA-256 of its command line, its declared source files, its declared toolchain inputs, and the keys of any upstream actions it depends on. Same key, same result — guaranteed.
3. **Explicit toolchains.** Languages and utilities don't come from the host `$PATH`; they're declared as `register_toolchains` entries and resolved deterministically based on the build configuration.

The practical consequence: if two engineers build the same commit, Bazel can prove the actions are byte-identical. That's the foundation that lets a remote cache work safely — and it's the foundation Buildbuddy leans on.

> The hermeticity guarantee is binary. Either an action is sandboxed and reproducible, or it isn't. Bazel makes this auditable via `bazel info` and `bazel build --check_visibility=false --verbose_failures //...` output.

## Patterns in Production: A Multi-Language Monorepo

Consider a realistic monorepo: Go services, a TypeScript frontend, Java backend, and a few Python ML jobs. Before Bazel, each language had its own toolchain pin, its own cache, and its own way of breaking. A typical CI run looked like:

- 12 minutes on `go build` from cold cache
- 8 minutes on `tsc` because `node_modules` was rebuilt
- 14 minutes on Maven because the CI runner's `~/.m2` was wiped weekly
- 6 minutes on pip resolution that occasionally picked different wheels

After a Bazel + Buildbuddy migration, the same workspace:

- **Go:** Actions are cached remotely; cold builds hit cache at 90%+ within a day.
- **TypeScript:** `node_modules` is declared via [`rules_nodejs`](https://github.com/bazelbuild/rules_nodejs), so the action key includes the lockfile and target OS. Replays are bit-identical.
- **Java:** [`rules_jvm_external`](https://github.com/bazelbuild/rules_jvm_external) hashes Maven artifacts by SHA; the resolver is part of the action key.
- **Python:** [`rules_python`](https://github.com/bazelbuild/rules_python) pins interpreters via `py_runtime` and tools via a hermetic `whl` distribution.

The same `bazel test //...` that took 40 minutes on raw CI now takes 6 — and that 6 is the same 6 the engineer saw on their laptop. That's the pitch.

## Setting Up Buildbuddy as Your Remote Backend

Buildbuddy is a self-hostable (or SaaS) remote build cache and execution service. It speaks the **Remote Execution API v2** ([REv2 spec](https://github.com/bazelbuild/remote-apis)) and **Remote Build Execution** protocols natively, so Bazel treats it as a peer.

### Step 1: Configure the `.bazelrc`

The canonical setup points Bazel at Buildbuddy for both caching and execution:

```bash
# .bazelrc
build:remote --remote_cache=grpcs://remote.buildbuddy.io
build:remote --remote_executor=grpcs://remote.buildbuddy.io
build:remote --remote_header=x-buildbuddy-api-key=YOUR_API_KEY

build:remote --bes_backend=grpcs://remote.buildbuddy.io
build:remote --bes_results_url=https://app.buildbuddy.io/invocation/
build:remote --bes_header=x-buildbuddy-api-key=YOUR_API_KEY

build:remote --remote_timeout=600
build:remote --jobs=50

# Tell Bazel to actually use the sandbox + remote
build:remote --spawn_strategy=remote,sandboxed,local
build:remote --strategy=Genrule=remote,sandboxed,local

# Platform mapping (so Buildbuddy picks the right workers)
build:remote --host_platform=@buildbuddy_toolchain//:platform
build:remote --platforms=@buildbuddy_toolchain//:platform
build:remote --extra_execution_platforms=@buildbuddy_toolchain//:platform
```

Note the **`--spawn_strategy=remote,sandboxed,local`** ordering — this tells Bazel: try remote execution first, then fall back to the local sandbox, then to plain local. You get speed when the cache hits, correctness guarantees when it doesn't, and graceful degradation under backend outage.

The Buildbuddy docs walk through this configuration in detail at [Buildbuddy's quickstart](https://www.buildbuddy.io/docs/quickstart).

### Step 2: Pick an Execution Platform

For reproducible results, your remote workers must run the same OS and architecture as your developers' machines. The [Buildbuddy toolchain](https://github.com/buildbuddy-io/buildbuddy/tree/master/tools/toolchains) registers Ubuntu 20.04 images by default; for Apple-silicon teams, you'll run local-only or use Linux ARM workers explicitly.

A minimal `WORKSPACE` registration:

```python
# WORKSPACE
http_archive(
    name = "buildbuddy_toolchain",
    urls = ["https://github.com/buildbuddy-io/buildbuddy-toolchain/archive/refs/heads/main.tar.gz"],
    strip_prefix = "buildbuddy-toolchain-main",
    sha256 = "REPLACE_WITH_ACTUAL_SHA",
)
load("@buildbuddy_toolchain//:rules.bzl", "buildbuddy_toolchains")
buildbuddy_toolchains()
```

### Step 3: Verify Hermeticity with `--remote_upload_local_results`

The killer flag for catching non-hermetic actions:

```bash
bazel test \
  --config=remote \
  --remote_upload_local_results \
  //...
```

This forces every locally executed action to upload its result to the cache. If an action is non-hermetic, the cache key still hashes the same way — but the result bytes diverge between machines, and you'll see the *cache hit ratio drop to zero for that target*. Buildbuddy's UI surfaces this directly: a target that always re-uploads is a target that's not actually hermetic.

This is the verification loop that turns hermeticity from a claim into a measurable property.

## Patterns in Production: Incremental Adoption

A common mistake is trying to migrate a 2,000-target repo in one quarter. Don't. The pattern that works:

1. **Start with a leaf target and one language.** Pick a Go service with no `protoc` step. Convert it to Bazel using [`gazelle`](https://github.com/bazelbuild/bazel-gazelle). Get it building on CI with Buildbuddy caching enabled.
2. **Lock the toolchain.** Once a service is green, pin its `go_sdk`, `nodejs`, or `java_toolchain`. *Don't* let CI reach into the system package manager.
3. **Gate on `diff_id=digest_aware` flakiness checks.** Use Buildbuddy's `BuildBuddy-Cache-Hit` result URL header to track hit ratios per target. Targets below 60% hit ratio after warmup are suspect.
4. **Move up the dependency graph.** Now that leaves are green, add intermediate libraries. Each new Bazel target inherits the cache from its leaves.
5. **Cut over CI entirely** once `bazel test //...` matches the legacy pipeline's coverage.

At each step, you keep shipping. You don't flip a switch.

## The Supply-Chain Upside: SLSA and Attestation

Hermeticity isn't just about speed. It's a prerequisite for the [SLSA Build Level 3](https://slsa.dev) guarantees — provenance that links a binary back to its exact source commit and build environment. Buildbuddy emits Build Event Stream records that include action keys, environment digests, and toolchain fingerprints.

Combine this with an attestation step:

```python
# In a rule's implementation
def _impl(ctx):
    out = ctx.outputs.out
    ctx.actions.run_shell(
        inputs = ctx.files.srcs,
        command = "build.sh > {out}".format(out = out.path),
        outputs = [out],
        # The sandboxed, hermetic action key gets recorded in BES
    )
    # Generate an in-toto-style attestation
    return [DefaultInfo(files = depset([out]))]
```

With the Build Event Protocol enabled, Buildbuddy records every action's command, environment, and inputs. You can later replay the build from just the source tree + the recorded metadata, producing bit-identical output. That's the SLSA-L3 contract.

> If your security team asks "can you prove this binary came from commit `abc123`?" — a Bazel + Buildbuddy pipeline answers with cryptographic action keys and signed Build Event Streams. No more screenshots of Jenkins logs.

## Common Pitfalls and How to Avoid Them

### Non-hermetic genrules

The classic trap: `genrule` that shells out to a binary the developer *thinks* is on `$PATH`. Bazel's sandbox hides the host `$PATH`. The fix is always to declare the tool as an explicit dep:

```python
genrule(
    name = "generate_proto",
    srcs = ["schema.proto"],
    outs = ["schema_pb2.py"],
    cmd = "$(location //tools:protoc) --python_out=$@ $<",
    tools = ["//tools:protoc"],  # declared, hermetic
)
```

The detail that breaks people is `cmd = "$(PATH)"` or any reference to `$HOME`, `/tmp`, or network URIs that aren't also in `srcs`. If you see "file not found" errors only on CI, that's the bug.

### Clock and timestamp leaks

`Date.now()` in a generated file, `date` in a `genrule`, git hashes from `git rev-parse HEAD` (rather than from a stamped build variable). These all break determinism. Use `--workspace_status_command` to inject git metadata as a build variable:

```bash
#!/usr/bin/env bash
echo "STABLE_GIT_SHA $(git rev-parse HEAD)"
echo "BUILD_TIMESTAMP 2024-01-01T00:00:00Z"  # frozen for reproducibility
```

Then reference `$(STABLE_GIT_SHA)` in your rules. The build becomes reproducible *and* traceable.

### Remote execution eviction

Remote caches can be GC'd. Buildbuddy's default retention is configurable; for release builds, don't rely on cache hits alone — store artifacts in a separate, longer-lived object store (GCS, S3) and verify them with SHA-256 before deploy.

## Key Takeaways

- **Hermeticity is a binary property.** Either your build is reproducible or it isn't; Bazel's sandbox plus action-key hashing is what makes it auditable, not just aspirational.
- **Buildbuddy extends hermeticity to the team.** A local Bazel build is hermetic per-machine; Buildbuddy makes it hermetic across the entire org via a remote cache that respects action keys.
- **The `--remote_upload_local_results` flag is your hermeticity test.** If a target keeps re-uploading, it's not actually hermetic. The cache hit ratio is a first-class correctness signal.
- **Pin your toolchains in `WORKSPACE`, not in your CI image.** Image drift is the silent killer of reproducible CI. Toolchain rules are versioned, hashable, and reviewed in code.
- **Hermeticity unlocks supply-chain guarantees.** SLSA Build Level 3 requires exactly the provenance Bazel + Buildbuddy produce out of the box.
- **Migrate incrementally.** Convert leaf targets first, gate on cache hit ratios, move up the dependency graph. Don't boil the ocean.

## Further Reading

- [Bazel — Hermeticity and Reproducibility](https://bazel.build/basics/hermeticity)
- [Buildbuddy Documentation — Quickstart and Configuration](https://www.buildbuddy.io/docs/quickstart)
- [Google Remote Execution API v2 Specification](https://github.com/bazelbuild/remote-apis)
- [SLSA — Supply-chain Levels for Software Artifacts](https://slsa.dev)
- [rules_python — Hermetic Python toolchains for Bazel](https://github.com/bazelbuild/rules_python)
- [Bazel Build Event Protocol Reference](https://bazel.build/docs/build-event-protocol)