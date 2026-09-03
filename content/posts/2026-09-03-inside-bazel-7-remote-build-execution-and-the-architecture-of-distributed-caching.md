---
title: "Inside Bazel 7: Remote Build Execution and the Architecture of Distributed Caching"
date: "2026-09-03T14:00:43.451"
draft: false
tags: ["bazel", "build-systems", "remote-execution", "distributed-caching", "developer-productivity"]
description: "A deep dive into Bazel 7's Remote Build Execution protocol, content-addressed caching, and the architecture that powers Google's monorepo builds."
summary: "How Bazel 7 splits a build graph across fleets of executors, what actually moves over the wire during remote execution, and why the content-addressable store makes distributed caching more than a performance trick."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-inside-bazel-7-remote-build-execution-and-the-architecture-of-distributed-caching.svg"
  alt: "Abstract network diagram showing a build graph split across remote executors and a shared content-addressable cache."
  caption: ""
  relative: false
---

> **TL;DR** — Bazel 7's Remote Build Execution is not "run my shell commands on a bigger machine." It is a tightly specified protocol that ships action inputs by digest, executes hermetically on remote workers, and returns outputs the client verifies against a Merkle-tree content-addressable store. The result is a build system where cache hits are correctness-preserving and parallelism scales linearly with fleet size.

If you have ever watched a clean rebuild of a medium-sized C++ monorepo grind for nine minutes while you know, *you know*, that ninety percent of those object files already exist somewhere on disk — Bazel's Remote Build Execution (RBE) is the answer to that specific kind of frustration. But the interesting story is not the wall-clock improvement. The interesting story is the architecture: how Bazel decomposes a build into a directed acyclic graph of actions, ships that graph to a remote service, and relies on cryptographic content addressing to make every cached byte trustworthy.

This post walks through Bazel 7's RBE stack — the Remote Execution API v2, the Action Cache, the Content Addressable Storage (CAS), and the executor model — with enough specificity that you can reason about failure modes and design your own integration. If you have used Bazel locally, most of these pieces already run on your laptop. RBE is what happens when you stop pretending the laptop is fast enough.

## What Bazel Actually Does Before Anything Goes Remote

Before we talk about RBE, it helps to remember that Bazel is already a distributed system in miniature. Every `bazel build` runs four cooperating processes: the **client** (your CLI), the **server** (the long-lived JVM that holds the action graph and dependency state), the **loader** for `WORKSPACE` and `MODULE.bazel` files, and the **worker pool** for individual actions.

When you run `bazel build //services/payments:api`, the server:

1. Parses the package and discovers the target's transitive dependencies.
2. Loads the **skyframe graph** — Bazel's incremental evaluation engine that ties actions to their inputs.
3. Walks the action graph bottom-up, asking each action's `exec_properties` which **spawn strategy** to use (`local`, `remote`, `sandboxed`, etc.).
4. Produces a fully ordered set of `(inputs, command, outputs)` tuples, each identified by a digest.

By the time a single byte leaves your machine for a remote backend, Bazel has already done a tremendous amount of work to make the remote step cheap. The action graph is hermetic, content-addressed, and stable across machines. That is the precondition that makes RBE possible at all — you cannot send arbitrary shell commands to a remote executor and expect caching to be correct. You can only send actions whose inputs are precisely known.

This is why RBE is described in [the Bazel documentation](https://bazel.build/remote/rbe) as "a specific subset of Bazel's local execution model," not a separate mode.

## The Remote Execution API v2: A Protocol, Not a Product

The wire format is defined by the [Remote Execution API v2](https://github.com/bazelbuild/remote-apis), an open specification maintained alongside Bazel itself. Three services matter:

- **ContentAddressableStorage (CAS)** — an append-only object store keyed by SHA-256 digest.
- **ActionCache (AC)** — a mapping from `Action` digest to `ActionResult` (exit code, stdout, stderr, output digests).
- **Execution** — a streaming RPC that takes an `Action` and a set of input root digests, and returns an `ExecuteResponse`.

The client-side entry point is the [`remote`](https://bazel.build/reference/command-line-reference#build) flag group. A minimal invocation looks like this:

```bash
bazel build //... \
  --remote_executor=grpcs://remotebuild.example.com:443 \
  --remote_instance_name=projects/payments/builds \
  --remote_cache=grpcs://remotebuild.example.com:443
```

The `--remote_instance_name` is not cosmetic. It is the **namespace** the backend uses to scope your CAS and AC entries. This is how Google runs millions of builds per day against a shared RBE fleet without one team's object files colliding with another's. Treat it like a database schema: pick a convention and never let it drift.

### The Digests That Hold It All Together

Every meaningful value in the protocol is a [`Digest`](https://github.com/bazelbuild/remote-apis/blob/main/build/bazel/remote/execution/v2/remote_execution.proto#L87) — a `(hash, size_bytes)` tuple where `hash` is lowercase hex SHA-256. Paths inside a directory tree do not identify files; **digests identify files**. Two directories with the same files in different orders produce the same root digest. That property is what lets Bazel reuse inputs across builds even when a tool rewrites a directory with slightly different mtimes.

Internally, Bazel represents each action as a Merkle tree:

```text
Action
 ├── command:        "gcc -c payments.cc -o payments.o"
 ├── input_root_digest: <tree digest>
 └── environment: []
```

The `input_root_digest` is the root of a `Tree` message that recursively references child `Directory` messages by digest. Leaf entries are either `file` nodes (with digest and executable bit) or `symlink` nodes. The whole tree is content-addressed, so if even one byte of any input changes, the root digest changes, the cache key changes, and the action is invalidated. There is no time-based invalidation. There are no TTLs. Correctness is a property of the hash function.

## Anatomy of a Remote Build

With the protocol clear, the actual lifecycle of a remote build is easier to follow.

### 1. Upload Phase (Bazelbyrd Phase)

Bazel walks the action graph and collects every `(Action, input root)` pair that has not been seen by the remote AC. For each unseen root, it computes the missing blobs and uploads them to the CAS as a `BatchUpdateBlobs` request:

```protobuf
message BatchUpdateBlobsRequest {
  InstanceName instance_name = 1;
  repeated Digest digest = 2;
  bytes data = 3;  // one entry per digest, packed
}
```

This is where Bazel's `--experimental_remote_cache_async` and the tree-based [`BatchReadBlobs`](https://github.com/bazelbuild/remote-apis/blob/main/build/bazel/remote/execution/v2/remote_execution.proto#L1136) optimizations matter. Bazel 7 sends uploads in parallel, deduplicates blobs by digest, and uses `ByteStream` for files larger than the configurable chunk size (default ~4 MiB). On a healthy connection, the upload phase is bandwidth-bound, not RPC-bound.

A practical tip: if your remote backend is on a different continent, the *upload* phase is often the wall-clock bottleneck, not execution. Tools like [`bazel-remote`](https://github.com/buchgr/bazel-remote) cache CAS objects at the edge for that exact reason.

### 2. Scheduling and Execution

Once the inputs are present, Bazel calls `Execute` on each action. The backend is responsible for:

1. Looking up the action in the AC. If the action digest exists **and** the input root is still present in the CAS, it returns the cached `ActionResult` immediately.
2. Otherwise, enqueueing the action on a worker pool. Workers pull a queued action, fetch missing blobs from the CAS, set up a sandbox, run the command, and stream stdout/stderr back.
3. Uploading outputs to the CAS and writing the `(Action digest → ActionResult)` mapping to the AC.

The scheduler is where the magic happens, and it is also the part Bazel itself does not implement — the remote backend chooses the scheduler. Google's internal [RBE](https://github.com/bazelbuild/bazel/blob/master/src/main/java/com/google/devtools/build/lib/remote/RemoteSpawnRunner.java) uses a two-tier queue: low-latency workers for fast actions (`go build`, `protoc`) and high-throughput workers for heavy C++ link steps. Open-source equivalents like [BuildBarn](https://github.com/buildbarn/bb-remote-execution) and [BuildBuddy](https://www.buildbuddy.io/) implement similar dispatch but with different fairness policies.

### 3. Download Phase

For actions whose outputs are consumed by later actions in the same build, Bazel does *not* download the output files. It just records the output digest. Outputs are only materialized locally when the build finishes and Bazel needs to surface them (for `bazel-bin`, runfiles, etc.). For a large remote build, the download phase can be just a few hundred kilobytes — the *metadata* of where outputs live in the CAS — because the actual blobs are referenced, not copied.

This is a subtle and underappreciated property. It is also why RBE plays so well with monorepos: a build graph with 200,000 actions moves about the same amount of metadata across the network as one with 20,000.

## Distributed Caching: Why It Is More Than a Performance Trick

There are three reasons distributed caching is structurally important, not just a nice-to-have:

### Cache Hits Are Correctness Guarantees

Because the cache key is a hash of inputs and command, a hit means *bitwise identical inputs and command*. There is no "best effort" reuse. If the cache says this action has been executed before with these exact inputs, the result is correct by construction. This is the property that lets you cut a CI build from 22 minutes to 90 seconds without re-running tests on a partial hit — you can trust the cache.

Compare this to `ccache`, where keying is heuristic (mtime + size + a compiler-defined hash). `ccache` is fast and useful, but it must be conservative because a wrong hit is silent corruption. Bazel's CAS-based caching is exact by design.

### Sharding Is Trivial

A cache backend does not need to understand your build. It only needs to understand digests. That means you can shard a CAS across storage pools, regions, or vendors without changing Bazel. Google's monorepo runs against multiple CAS deployments; local teams can run a [`bazel-remote`](https://github.com/buchgr/bazel-remote) proxy that talks to a shared backend for hot data and a local backend for cold data. [BuildBuddy's](https://github.com/buildbuddy/buildbuddy) hybrid cache uses this same trick.

### Cross-Machine Reuse Is the Default

This is the headline benefit. In a Google-scale monorepo, a developer pushing a change to a leaf package reuses the compiled outputs of the other 99% of the tree from the shared cache. The "no-op change" build — changing a comment — completes in seconds because almost every action's inputs and command digest are unchanged.

## Patterns in Production

A few patterns show up over and over when teams deploy Bazel RBE at scale.

### The Three-Tier Cache

Most mature setups run three cache layers in front of the AC/CAS:

1. **Local disk cache** (`--disk_cache=/var/cache/bazel`) for offline work and laptop builds.
2. **Self-hosted HTTP/grpc cache** (`bazel-remote`, BuildBuddy, BuildBarn) inside the corporate network.
3. **Managed cache** (Google's, EngFlow's, or a vendor's) as the authoritative source.

Bazel consults them in order, writes through to all of them, and uses content addressing to deduplicate. The configuration looks like:

```bash
--disk_cache=/var/cache/bazel
--remote_cache=grpc://bazel-remote.internal:9092
--remote_cache=grpcs://cache.buildbuddy.io
--experimental_remote_cache_async
```

### Hermetic Toolchains

RBE exposes a problem you could ignore when building locally: **your toolchain must be hermetic**. If your action shells out to `/usr/bin/clang` and the remote executor does not have that clang at that exact version, the build silently produces different binaries. Bazel's [`rules_cc`](https://github.com/bazelbuild/rules_cc) and [`rules_rust`](https://github.com/bazelbuild/rules_rust) toolchains solve this by registering a fully hermetic compiler under the [`platforms`](https://bazel.build/extending/platforms) system. The action then ships the compiler as an input to the CAS, identified by digest.

### `exec_properties` for Executor Affinity

Not all actions are equal. A `clang -E` action is latency-sensitive; a deep `lto` link is throughput-sensitive. Bazel's `exec_properties` let you tag actions with hints that the backend scheduler can honor:

```python
cc_library(
    name = "payments_proto",
    srcs = ["payments.proto"],
    exec_properties = {
        "no-cache": "false",
        "Pool": "high-cpu",
        "container-image": "docker://gcr.io/payments/rbe-ubuntu@sha256:...",
    },
)
```

BuildBarn and BuildBuddy honor the `Pool` key; EngFlow's backend supports arbitrary keys via its scheduler config.

### Handling Non-Determinism

Even hermetic toolchains can produce non-deterministic outputs (timestamps, UUIDs, randomized test ordering). The fix is to either normalize in the toolchain (`SOURCE_DATE_EPOCH=0`, `-frandom-seed=...`) or to mark the action as `"no-remote-cache": "true"`. The latter is a sledgehammer; the former is what you actually want.

## Failure Modes Worth Naming

RBE introduces categories of failure that local builds do not have.

- **CAS divergence**: Two workspaces claim the same digest but produce different blobs. This should be cryptographically impossible; if you see it, the bytes that were hashed differ from the bytes that were uploaded. Debug with `bazel dump --rules` and check for `volatile-status` or symlink races.
- **AC poisoning**: A cache key was written with the wrong outputs. This happens when an action's outputs are not fully declared in the rule. Bazel 7 catches most cases via [`--remote_download_minimal`](https://bazel.build/remote/caching#repository-cache) and `--remote_grpc_log`, but the long-term fix is to add the missing `outputs` to the rule.
- **Executor starvation**: The backend's worker pool is saturated. Symptoms are long queue times with low CPU on the workers. The fix is either to provision more workers or to break the action into smaller sub-actions. Tools like [Bazel Insights](https://blog.buildbuddy.io/introducing-bazel-insights/) help identify the worst offenders.
- **Network partitions**: A flaky link between client and remote can cause partial uploads that look like missing inputs. Bazel retries by default, but for very long-running actions, configure `--remote_max_connections` and `--experimental_remote_cache_compression` to reduce churn.

## Bazel 7 Specific Improvements Worth Knowing

Bazel 7 shipped several RBE improvements that are easy to miss in the release notes:

- **`--experimental_remote_cache_compression`** now defaults to `true` for uploads, with zstd instead of gzip. Expect ~20% less bandwidth on text-heavy CAS uploads.
- **Tree artifact support** in the `BatchReadBlobs` path reduces RPC count for large source trees by ~70% in published benchmarks.
- **Persistent workers over RBE** via `--remote_worker` lets long-lived tools (`scalac`, `rustc` servers) keep state across actions, removing per-action startup overhead.
- **Streamed CAS uploads** via [`ByteStream.Write`](https://github.com/bazelbuild/remote-apis/blob/main/build/bazel/remote/execution/v2/remote_execution.proto#L471) are now the default, eliminating the previous memory blowup on multi-gigabyte inputs.

## Key Takeaways

- Bazel's RBE is a *protocol* on top of an already-distributed build graph; correctness comes from content addressing, not from trusting the executor.
- The Action Cache and Content Addressable Storage are separate services with separate consistency models; treat them as such in your configuration.
- Cache hits are correctness-preserving because the key is a cryptographic hash of all inputs and the command — no timestamps, no heuristics.
- Most production RBE setups run a three-tier cache (local disk, self-hosted, managed) with content addressing making the tiers invisible to Bazel.
- Toolchain hermeticity is non-optional; without it, your cache silently lies.
- Bazel 7's compression defaults and tree artifact batching meaningfully reduce network cost on cold builds.

## Further Reading

- [Remote Execution API v2 specification](https://github.com/bazelbuild/remote-apis) — the wire protocol every RBE backend speaks.
- [Bazel Remote Execution documentation](https://bazel.build/remote/rbe) — the authoritative guide to flags and configuration.
- [BuildBarn: a fully open-source RBE backend](https://github.com/buildbarn/bb-remote-execution) — the cleanest open implementation of the spec.
- [bazel-remote cache proxy](https://github.com/buchgr/bazel-remote) — the de facto standard self-hosted cache.
- [BuildBuddy's RBE architecture overview](https://www.buildbuddy.io/docs/rbe-setup) — production patterns and pitfalls from a managed vendor.
- [EngFlow's "Hermetic Toolchains with Bazel" guide](https://docs.engflow.com/docs/toolchains) — practical advice for getting toolchain hermeticity right.