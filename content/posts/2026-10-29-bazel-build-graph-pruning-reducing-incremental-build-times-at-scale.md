---
title: "Bazel Build Graph Pruning: Reducing Incremental Build Times at Scale"
date: "2026-10-29T01:01:09.999"
draft: false
tags: ["Bazel", "Build Systems", "Incremental Builds", "Monorepo", "CI/CD"]
description: "Learn how Bazel build graph pruning reduces incremental build times at scale, with patterns for monorepos, remote execution, and production CI pipelines."
summary: "Bazel's build graph pruning skips irrelevant targets during incremental builds. This post covers how it works, when it breaks down, and production patterns for keeping monorepo CI fast."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-29-bazel-build-graph-pruning-reducing-incremental-build-times-at-scale.svg"
  alt: "Bazel build dependency graph with pruned subtrees highlighted"
  caption: ""
  relative: false
---

> **TL;DR** — Bazel build graph pruning avoids rebuilding the entire dependency graph by only evaluating targets affected by changed files. At monorepo scale, pruning is the difference between a two-minute incremental build and a forty-minute full rebuild, but it depends on accurate file ownership, correct output grouping, and disciplined use of `exports_files` and `filegroup`.

Bazel’s promise is reproducible, incremental builds, but that promise erodes as a monorepo grows. In a small repository, `bazel build //...` finishes fast enough that nobody notices. In a repository with thousands of packages and millions of lines of code, the same command can spend minutes just loading and analyzing BUILD files before a single compiler runs. The problem is rarely that Bazel is slow at executing actions; it is that Bazel spends too much time deciding what to execute.

Build graph pruning is Bazel’s answer to that decision cost. Instead of analyzing every target in the workspace, Bazel identifies the subset of the dependency graph touched by a change and ignores everything else. When it works, an incremental build touches only a few hundred targets instead of tens of thousands. When it does not work, you pay for a full rebuild and wonder why your CI queue is backed up.

This post explains how pruning works, where it breaks down at scale, and the production patterns that keep monorepo builds fast.

## Why Incremental Builds Break Down at Scale

Bazel divides a build into two phases: analysis and execution. During analysis, Bazel loads BUILD files, evaluates rules, and constructs the action graph—a directed acyclic graph of concrete commands like compile, link, and test. During execution, it runs those actions, caching outputs by content hash.

In theory, only changed files should trigger re-analysis. In practice, the analysis phase walks the entire workspace topology to determine reachability. If your repository has 4,000 packages, Bazel must at least inspect the BUILD files and dependency edges for all of them before it can conclude that most are unaffected. That cost is linear in repository size, not in change size, and it dominates incremental builds long before execution becomes the bottleneck.

Three named failure modes accelerate this collapse:

* **Transitive dependency explosion.** A change to a low-level library such as `//base:logging` invalidates every target that transitively depends on it. In a monorepo, that can be half the repository.
* **Broad file globs.** A `srcs` attribute using `glob(["**/*.cc"])` causes Bazel to treat any new or deleted file in that directory as a potential input to every target using that glob.
* **Toolchain churn.** Upgrading the C++ toolchain or Java version invalidates action keys for every compiled target, forcing a full rebuild even when no source changed.

The result is a CI pipeline where a one-line change triggers a thirty-minute build, and engineers stop trusting incremental verification.

## How Bazel Build Graph Pruning Works

Pruning operates during the analysis phase. When Bazel detects that a set of files changed—through its in-process file system watcher locally, or through a `git diff` fed into CI—it marks those files as dirty. It then walks the reverse dependency graph from the targets that directly consume those files, collecting only the targets that must be re-analyzed. Targets outside that reverse dependency cone are skipped: their packages are not loaded, their rules are not evaluated, and their actions are not added to the graph.

The output is a pruned action graph. If you changed `//lib/core:utils.cc`, Bazel analyzes `//lib/core:utils_lib`, the binaries and tests that depend on it, and nothing else. A service in an unrelated directory that does not depend on `utils_lib` is invisible to this build.

You can inspect this behavior with Bazel’s query tools. `bazel query` operates on the target graph, while `aquery` operates on the action graph and is more useful for understanding pruning because it shows concrete actions and their inputs. For example:

```bash
bazel aquery --output=textproto '//depset of affected targets'
```

The exact invocation depends on your CI, but the principle is constant: compute the affected set, then build only that set.

Pruning also interacts with output groups. If a target produces multiple outputs through a `filegroup`, Bazel can prune individual outputs within a target when only some are requested via `--output_groups`. This is less commonly used than target-level pruning, but it matters for large targets that generate both a binary and a debug symbol package.

## The Analysis Phase Is the Hidden Tax

Pruning reduces the number of targets Bazel must analyze, but it does not eliminate analysis cost for the targets that remain. If your changed file is consumed by 300 targets, Bazel still re-analyzes all 300. If those targets use aspects—for example, to generate proto stubs or lint reports—each aspect runs during analysis and multiplies the cost.

Repository rules are another analysis-phase trap. A repository rule that fetches external dependencies runs during loading, and if its output changes, Bazel invalidates every target that depends on the external repository. Keep repository rules hermetic and pin their versions aggressively.

Bazel’s persistent workers speed up execution by keeping compiler processes alive across builds, but they do not help analysis. If your analysis phase takes three minutes, persistent workers cannot save you. You must keep the analyzed graph small.

Tools like [buildifier](https://github.com/bazelbuild/buildtools) and [buildozer](https://github.com/bazelbuild/buildtools) help here by enforcing clean BUILD file structure, which makes it easier for Bazel to load packages quickly and for humans to see dependency boundaries.

## Architecture: Pruning in a Monorepo with Remote Execution

At scale, pruning is only half the story. The other half is remote execution and remote caching. In a typical production architecture, CI looks like this:

1. A pull request triggers a `git diff` against the base branch.
2. CI computes the set of affected packages and targets.
3. CI runs `bazel build` or `bazel test` against only that pruned set.
4. Bazel checks the remote cache for action outputs. Cache hits skip execution entirely.
5. Cache misses are dispatched to remote executors (such as Google RBE or Buildbarn), which compile and test in parallel.
6. Results are written back to the remote cache for the next build.

This architecture turns pruning from a local optimization into a system-wide force multiplier. Consider a concrete scenario: a monorepo with 8,000 targets. A developer changes two files in a shared authentication library. Without pruning, Bazel analyzes all 8,000 targets and CI queues thousands of actions. With pruning, Bazel analyzes 320 targets. Of those, 280 are remote cache hits from previous builds. Only 40 actions execute remotely, finishing in roughly ninety seconds instead of thirty-five minutes.

The persistent Bazel daemon (`bazel --batch` vs. long-running server) matters here too. A long-running server keeps the file system state in memory, so incremental builds start faster. In CI, where containers are ephemeral, you lose that advantage unless you warm the cache, which makes remote caching even more critical.

## Patterns in Production: Keeping the Graph Small

Pruning works best when the dependency graph is fine-grained and explicit. The following patterns keep the pruned graph small and the cache hit rate high.

### Fine-grained packaging

Avoid mega-packages with dozens of targets in a single BUILD file. One BUILD file per library, or even per major component, keeps the analysis surface small. When a file changes, Bazel only needs to load the package that owns it, not a monolithic package containing unrelated code.

### Narrow `srcs`

Prefer explicit file lists over broad globs. `glob(["**/*.cc"])` is convenient but causes over-invalidation: any file added or removed under that directory marks every target using the glob as potentially dirty. Explicit `srcs` lists make the file-to-target relationship precise.

### Discipline with `filegroup` and `exports_files`

Use `filegroup` to share data files between targets without creating implicit dependencies on directory contents. Use `exports_files` only when a file must be visible outside its package. Over-exporting creates visibility edges that widen the reverse dependency cone and reduce pruning effectiveness.

### Direct dependencies only

Bazel enforces that targets declare their direct dependencies, but teams sometimes work around this by relying on transitive headers or libraries. That weakens pruning because a change to a transitive dependency can appear as a direct input to more targets than necessary. Keep `deps` lists tight.

### Visibility and `package_group`

Use `package_group` and `default_visibility` to prevent accidental coupling between unrelated parts of the repository. If two services should not depend on each other, enforce it at the package level so Bazel never considers them part of the same affected cone.

### CI affected-target computation

Do not run `bazel build //...` on every pull request. Instead, compute affected targets from `git diff --name-only` and feed them to Bazel. Some teams wrap this in a small script that calls `bazel query` or `aquery` to expand file changes into target sets. The exact tooling matters less than the rule: build only what changed.

### Pin toolchains and avoid `stamp`

Toolchain changes invalidate every action keyed to that toolchain. Pin your C++, Java, and Go toolchain versions in `.bazelrc` or WORKSPACE equivalents. Similarly, avoid `stamp = True` on binaries unless you need SCM revision information in the binary; stamping embeds build metadata that changes with every commit, defeating cache reuse.

## When Pruning Fails: Named Failure Modes

Even with good hygiene, pruning can degrade. Know the failure modes so you can diagnose them quickly.

**Broad glob over-invalidation.** A `glob` that matches generated files causes Bazel to re-analyze consumers whenever codegen runs, even if the generated content is identical.

**Generated file churn.** Code generation steps that emit timestamps or build IDs into output files invalidate downstream consumers. Make codegen deterministic so identical inputs produce identical outputs.

**Shared low-level dependencies.** A change to `//base:logging` or `//common:config` cascades to hundreds of targets. There is no technical fix for this; it is a property of the dependency graph. Mitigate by versioning shared libraries so consumers opt in to new versions rather than pulling the latest automatically.

**Incompatible flags.** Bazel releases `--incompatible_*` flags that change rule semantics. Enabling one mid-repository can invalidate action keys across the board. Roll them out branch by branch, not repository-wide.

**Sandboxing and symlink races.** Bazel’s sandbox can create false positives when file permissions or symlinks change without content changes. If you see unexpected rebuilds, check `--spawn_strategy` and sandbox settings.

**Shared library relinking.** Changing a shared library causes every binary that links against it to relink, even if the public API did not change. Where possible, prefer static linking for internal libraries to localize the cost of changes.

## Measuring Pruning Impact

You cannot improve what you do not measure. Bazel emits a profile file that you can analyze with `bazel analyze-profile`. Key metrics to track per build:

* **Analysis time:** Time spent loading BUILD files and constructing the action graph. Pruning should reduce this proportionally to the pruned target count.
* **Total actions:** Number of actions in the graph. A full build might have 12,000 actions; a pruned build should have hundreds.
* **Cache hit rate:** Percentage of actions served from remote cache. Pruning plus caching should push this above 90% for incremental builds.
* **Critical path:** The longest chain of dependent actions. Even a small graph can be slow if its critical path is long.

A representative production baseline might look like this:

| Metric | Full Build | Pruned Incremental Build |
|--------|------------|--------------------------|
| Targets analyzed | 8,000 | 320 |
| Actions | 12,000 | 400 |
| Remote cache hits | 0% | 90% |
| Actions executed | 12,000 | 40 |
| Wall clock time | 35 minutes | 90 seconds |

Track these numbers in your CI dashboards. If the pruned build’s action count creeps upward over time, you likely have glob creep or a new shared dependency that is widening the affected cone.

## Key Takeaways

* Bazel build graph pruning limits analysis and execution to targets affected by changed files, turning repository-scale builds into change-scale builds.
* Pruning happens during analysis; persistent workers and remote execution speed up execution but do not fix slow analysis.
* Fine-grained packaging, narrow `srcs`, and disciplined `filegroup`/`exports_files` usage keep the pruned graph small.
* Combine pruning with remote caching so unchanged targets are cache hits rather than re-executed actions.
* Watch for named failure modes: broad globs, generated file churn, shared low-level dependencies, incompatible flags, and toolchain changes.
* Measure with `bazel analyze-profile` and track analysis time, action count, and cache hit rate in CI.

## Further Reading

* [Bazel documentation](https://docs.bazel.build/)
* [Bazel Query How-To](https://docs.bazel.build/7.0/query.html)
* [Remote Caching in Bazel](https://docs.bazel.build/7.0/remote-caching.html)
* [Bazel Blog](https://blog.bazel.build/)
* [Buildbarn Documentation](https://docs.buildbarn.io/)

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
