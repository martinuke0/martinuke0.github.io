---
title: "Inside LLVM's New Pass Manager: A Deep Dive into Its Architecture"
date: "2026-10-02T18:01:02.942"
draft: false
tags: ["llvm", "compilers", "pass-manager", "optimization", "compiler-architecture"]
description: "A deep dive into LLVM's new pass manager architecture, covering its design principles, data flow, and production implications for compiler engineers."
summary: "Exploring LLVM's new pass manager: architecture, design patterns, and how it transforms modern compiler optimization."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-02-inside-llvm.svg"
  alt: "LLVM pass manager architecture diagram"
  caption: ""
  relative: false
---

> **TL;DR** — LLVM's new pass manager replaces the legacy global manager with a modular, dependency-aware architecture that enables finer-grained optimization pipelines, better cost modeling, and seamless interoperability with modern tooling like MLIR. Its design centers on per-function pass sequences, explicit dependency tracking, and a cost-model-driven execution order that reduces redundant IR passes and improves compilation throughput.

The pass manager is the orchestration layer that decides *when* and *in what order* LLVM applies optimization transformations to the intermediate representation. Since LLVM 11, the project has been gradually transitioning from the legacy pass manager to a new design that addresses scalability bottlenecks, supports incremental compilation, and provides a cleaner API for pass authors. This article dives into the new pass manager's core architecture, the design patterns it leverages, and what it means for engineers building or extending compiler pipelines today.

## The Evolution of LLVM's Pass Management

The legacy pass manager, which shipped with LLVM's initial releases, relied on a globally registered list of passes. Pass authors would `registerPass()` their transformation, and the builder would stitch them together into a `PassManager` based on command-line flags `-passes` or optimization level `-O0` through `-O3`. While functional for many years, this design hit several walls as compiler workloads grew:

- **No per-function sequencing**: The legacy manager applied the same pass sequence uniformly across all functions, making it difficult to express function-specific optimization strategies without hacky flag plumbing.
- **Ad-hoc cost modeling**: Cost estimates for pass ordering lived outside the pass infrastructure, often duplicated across passes or inferred heuristically, leading to suboptimal schedules for large functions or tight compilation-time budgets.
- **Compilation time scaling**: At `-O3`, the number of IR passes could balloon past 150, and without explicit dependency tracking, the manager would re-run analyses and transformations that preserved prior results, wasting CPU cycles.

The new pass manager, introduced in LLVM 11 and stabilized through releases 15 and 16, was designed specifically to resolve these constraints. Its guiding principle: *explicit dependencies, explicit ordering, explicit cost*. By making the IR data-flow graph visible to the scheduler, the new PM can skip passes whose results are already preserved, and it can order passes to minimize redundant analysis rereading.

## Architectural Pillars of the New Pass Manager

### Dependency-Aware Pass Scheduling

At the heart of the new pass manager lies a directed acyclic graph (DAG) of pass *instances*. Each pass subclasses `PassInfoMixin<Derived, ArchTag>` and declares which IR analyses it requires and which it preserves. The framework builds the pass DAG at pipeline construction time by introspecting these `getPreservedID()` and `getRequiredID()` methods. When the pipeline executes, it topologically sorts the DAG, ensuring that any analysis needed by a pass has already run—and that if a prior pass claims it preserves an analysis, that analysis is skipped.

This design enables a powerful pattern: *analysis caching*. If pass A requires `DominanceAnalysis` and pass B claims it preserves `DominanceAnalysis`, the new PM will run `DominanceAnalysis` once, before pass A, and then skip it before pass B. In practice, this reduces the total number of analysis runs by 30–50% in typical `-O2` pipelines, as measured on the LLVM testsuite.

### Cost Modeling and Heuristic Scheduling

The new pass manager ships with a cost model infrastructure located in `llvm/Passes/Passes.h` and `llvm/Passes/PassBuilder.h`. Pass authors can override `getPassCost()` to declare the relative expense of their transformation in terms of compile time and IR size impact. The scheduler uses these costs to resolve ordering ambiguities when multiple valid topological orderings exist.

For example, if pass X has a cost of 5 and pass Y has a cost of 2, and both are valid at the same DAG level, the scheduler will prefer Y first, thereby reducing early-stage compile-time pressure. Users can also supply a custom cost model via `-mllvm -cost-model=`, which is particularly useful for domain-specific compilers building on LLVM (e.g., embedded workflows where flash size matters more than compile time).

Crucially, the cost model is *additive*: the total pipeline cost is the sum of individual pass costs plus a small penalty for each inter-pass analysis reload. This granular accounting lets the scheduler prune expensive passes from the pipeline when the user passes `-mllvm -enable-new-pm-only` and opts into a minimal pass set.

### Pipeline Construction and Execution

The new pass manager introduces three primary pipeline entities:

1. **`ModulePassManager`** – operates on the entire module, suitable for interprocedural passes like inlining, whole-program optimization, and bitcode writing.
2. **`FunctionPassManager`** – operates on a single function, ideal for function-level transformations such as instcombine, GVN, and loop passes.
3. **`PassManager`** – a lightweight wrapper that can execute either a module-level or function-level pipeline, selected at construction time.

Pipelines are built using the `PassBuilder` API, which provides fluent methods like `addPipelinePass<>` to inject a pass into a specific stage (e.g., "early", "loop", "late"), and `addPassesFromString()` to parse `-passes` flags. The execution loop calls `runOnFunction()` or `runOnModule()` depending on the manager type, and internally handles materializing the required analyses before each pass's execution.

A notable production feature is the ability to query and modify the pipeline *after* construction. The `PassManager` exposes `printPipeline()` for debugging, and `passes()` returns the ordered list, enabling tools and IDEs to visualize the optimization journey—a capability that was notably absent from the legacy manager.

## Patterns in Production: Optimization Pipelines

### The -O0 through -O3 Pipeline

The new pass manager powers the `-O0` through `-O3` optimization levels since LLVM 15. Each level maps to a preconstructed pipeline:

- **-O0**: Minimal transformation. The pipeline runs only `simplifycfg` and `tailcallelim`, focusing on correctness rather than performance. Compile time is sub-millisecond for typical source files.
- **-O1**: A balanced set targeting speed without aggressive IR expansion. Includes `instcombine`, `gvn`, `deadargelim`, and `correlatedvalueprop`. The pass count typically hovers around 15–20.
- **-O2**: The default "optimize for speed" level. Adds loop passes (`loop-rotate`, `loop-deletion`, `loop-vectorize` when enabled), `sroa`, and `dce`. The pipeline typically executes 35–50 passes, with the new PM’s dependency tracking keeping analysis reruns in check.
- **-O3**: Aggressive optimization. Enables `-O2` plus `scalar-repl-mem`, `aggressive-instcombine`, and the `always-inline` pass for functions marked `inline` or with `always_inline` attribute. Pass counts can reach 80–120, but the new PM’s cost-aware scheduling helps mitigate compile-time blowup.

Users can inspect the exact pipeline for any level with `opt -passes=help -O3 2>&1 | head -30`, which lists passes in execution order—a practical trick for debugging unexpected IR changes.

### Inlining and Interprocedural Optimization

Inlining remains one of the most impactful passes in any optimization pipeline. The new pass manager’s `Inliner` pass has been rewritten to integrate with the dependency framework: it now declares a requirement on `CallGraphWrapperPass` and preserves `CallGraph` across transformations that don’t modify call sites. This means the call graph is built once and reused across multiple inlining decisions, reducing redundant graph walks.

Interprocedural passes like `ipsccp` (Interprocedural Sparse Conditional Constant Propagation) and `correlatedvalueprop` similarly benefit from the new PM’s ability to share analyses across function boundaries when the `CallGraph` is preserved. In production benchmarks compiling the SPEC CPU2017 suite with `-O2`, the new PM reduced total pass execution time by ~12% compared to the legacy manager, primarily by eliminating repeated `CallGraph` and `DominanceAnalysis` reconstructions.

### Vectorization and Loop Transformations

Loop passes in the new PM, particularly `loop-vectorize` and `loop-unroll`, are annotated with explicit cost models and dependency requirements. The scheduler respects loop-carried dependency analysis results, preventing the vectorizer from running before a `loop-dep` pass that would invalidate its assumptions. This ordering discipline has helped stabilize vectorization behavior across LLVM releases—a historically fragile area where the legacy manager’s implicit ordering often led to “vectorizer skipped: analysis not available” errors.

A concrete production scenario: compiling a digital signal processing workload (e.g., FFmpeg’s DCT pipeline) with `-mllvm -enable-new-pm=1 -O2` yields a 1.8% speedup in the generated binary versus the legacy `-O2`, with compile time increasing by only 3%—a favorable tradeoff attributable to the new PM’s leaner analysis schedule.

### Custom Pass Sequences for Domain-Specific Optimization

The new PM’s API is deliberately composable. Domain-specific compilers (e.g., for GPU kernels, cryptographic primitives, or embedded DSP workloads) can construct custom `FunctionPassManager` instances that run only the passes relevant to their optimization space. The `PassBuilder` allows inserting passes at arbitrary pipeline stages, and the `PipelineElement` enum exposes hooks like `preservedAnalyses`, `requiredAnalyses`, and `analysisUsage` for fine-grained control.

For example, a fuzzer-guided fuzzer might construct a pipeline that runs `instcombine` followed by a custom `SimplifyTriggers` pass, then `verifier`, skipping all loop and interprocedural passes entirely. This selective execution reduces compile time to a few milliseconds while still enabling meaningful IR simplification for coverage-guided mutational fuzzing.

## Migration Interop and Compatibility

### Legacy-to-New Migration Path

LLVM 16 ships with the `convertLegacyPassToNewPass` utility, which attempts to automatically translate a legacy pass into its new-PM equivalent. The conversion is not always perfect—legacy passes that relied on global state or `PassManagerBuilder` callbacks may require manual adaptation—but the tool provides a scaffold that significantly reduces boilerplate.

The `PassManagerBuilder` class, which drove legacy pipeline construction, is now deprecated. Authors migrating their passes should subclass `PassInfoMixin` and implement `run()`, `getPreservedID()`, and `getRequiredID()`. The new PM also introduces `AnalysisInfoMixin` for analyses, mirroring the pass structure and enabling the same dependency-aware scheduling benefits.

### Interoperability with MLIR

The new pass manager’s design was partially motivated by MLIR’s pass infrastructure, and the conceptual overlap is evident. Both frameworks treat passes as first-class objects with explicit analysis requirements, both use `Mixin` patterns for CRTP-style code reuse, and both favor composition over global registration. However, the new LLVM PM remains tightly coupled to the LLVM IR, while MLIR passes operate on MLIR dialects.

Tools like `pdll` (Pass Definition Language) still generate legacy PM passes, but the community is actively adding `pdll` backends that emit new-PM-compatible C++ code. For projects bridging LLVM and MLIR (e.g., polyhedral compilation via Polly, or tensor dialect optimizations), the new PM provides a familiar entry point without requiring a full MLIR pass rewrite.

### Gradual Adoption Strategy

Projects can opt into the new pass manager via the `LLVM_ENABLE_NEW_PASS_MANAGER=1` CMake option or the `LLVM_ENABLE_NEW_PASS_MANAGER` environment variable. This flag defaults to `off` in LLVM 15 but becomes `on` by default in LLVM 17. The gradual rollout strategy allows downstream distributors (e.g., Debian, Fedora) and commercial toolchains (e.g., compiler vendors building on LLVM) to test the new PM alongside the legacy one, filing bugs and performance regressions before the legacy manager’s eventual deprecation.

A practical migration pattern: run `opt -passes=...` under both managers and compare pipeline costs and execution times. In practice, the new PM’s cost-aware scheduling often yields tighter pipelines, but edge cases exist—particularly for passes that rely on legacy global pass registration hooks.

## Key Takeaways

- The new pass manager replaces the legacy global-pass-list design with a dependency-aware DAG scheduler, enabling explicit ordering and analysis caching that reduces redundant IR passes by 30–50% in typical pipelines.
- Core architectural pillars—dependency-aware scheduling, cost modeling, and modular pipeline construction via `PassBuilder`—provide granular control over compile-time optimization tradeoffs, making the new PM suitable for both general-purpose and domain-specific compilers.
- Production pipelines powered by the new PM (`-O0` through `-O3`) exhibit predictable pass counts and improved compile-time scaling, with `-O2` typically running 35–50 passes and `-O3` reaching 80–120 while preserving the analysis reuse benefits.
- The new PM’s explicit `getPreservedID()` / `getRequiredID()` contract simplifies migration from legacy passes and enables interoperability with MLIR-style pass infrastructures, though manual adaptation is required for passes relying on global registration.
- Gradual adoption is facilitated by `LLVM_ENABLE_NEW_PASS_MANAGER`, allowing side-by-side comparison with the legacy manager before the latter’s eventual deprecation in future LLVM releases.

## Further Reading

- [LLVM Pass Manager Documentation](https://llvm.org/docs/PassManager/)
- [LLVM Passes Reference](https://llvm.org/docs/Passes.html)
- [MLIR Pass Engine Overview](https://mlir.llvm.org/docs/PassEngine/)

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
