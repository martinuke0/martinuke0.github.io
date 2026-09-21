---
title: "Deep Dive into GraalVM Partial Evaluation"
date: "2026-09-21T18:01:29.993"
draft: false
tags: ["GraalVM", "Partial Evaluation", "JVM", "Native Image", "Performance", "Compiler"]
description: "A comprehensive deep dive into GraalVM's partial evaluation engine — how it works, why it matters, and how it powers both high-performance JVM execution and native compilation."
summary: "Explore GraalVM's partial evaluation, the foundational technique behind Truffle-based language interpreters and Native Image compilation. Learn how it transforms runtime performance through AST specialization, constant folding, and escape analysis."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-21-deep-dive-into-graalvm-partial-evaluation.svg"
  alt: "GraalVM logo and abstract compiler visualization representing partial evaluation"
  caption: "GraalVM's partial evaluation pipeline transforms generic bytecode into specialized, optimized machine code."
  relative: false
---

> **TL;DR** — GraalVM's partial evaluation is a meta-tracing compilation technique that specializes generic programs against known runtime constants, producing lean, optimized code. It is the engine behind both the GraalVM JIT compiler's deoptimization capabilities and the Truffle framework's language implementation strategy. Understanding it unlocks a fundamentally different mental model for JVM performance.

## What Is Partial Evaluation?

Partial evaluation is a program optimization technique formalized by Jones in 1979. The core idea is deceptively simple: given a program with some inputs known at compile time, specialize the program by folding those known constants into the computation, producing a residual program that is faster because it does not need to recompute what is already known.

In the context of GraalVM, partial evaluation takes this concept and applies it aggressively at the bytecode level. When the GraalVM compiler encounters a method being executed, it does not simply compile it to machine code as a black box. Instead, it constructs an abstract syntax tree (AST) representation of the method and then performs *partial evaluation* — treating the current execution path's inputs as constants and specializing the AST accordingly.

This is fundamentally different from traditional JIT compilation. A conventional JIT compiler like C2 (the server compiler in HotSpot) performs optimizations such as inlining, loop unrolling, and dead code elimination on the compiled method as a whole. GraalVM's partial evaluation goes further: it peels away layers of abstraction that are provably irrelevant for the current execution context.

Consider a method that reads a configuration value once and branches on it:

```java
public int process(int input) {
    int mode = Config.getMode(); // Returns a constant at runtime
    if (mode == 1) {
        return input * 2;
    } else {
        return input + 10;
    }
}
```

A traditional JIT might inline `Config.getMode()` and then eliminate the dead branch. GraalVM's partial evaluation will, during the partial evaluation pass, recognize that `Config.getMode()` is a constant and fold it directly into the AST, producing a residual program that is literally just `return input * 2` — with no conditional, no method call, and no branching overhead whatsoever.

## The Architecture of GraalVM Partial Evaluation

### The AST and the Partial Evaluation Loop

At the heart of GraalVM's partial evaluation lies a structured representation of the program. When the compiler enters a method, it builds a graph-based AST where nodes represent operations (loads, stores, arithmetic, method invocations) and edges represent data and control flow dependencies. This graph is not just an intermediate representation — it is the *work surface* on which partial evaluation operates.

The partial evaluation loop proceeds as follows:

1. **Introspection**: The compiler inspects each node in the AST. For each node, it asks: "Can I evaluate this node given the known constants?"
2. **Constant Folding**: If all inputs to a node are known constants, the node is replaced with its computed result.
3. **Specialization**: If a node represents a method call and the target method is known, the compiler recursively enters that method's AST and specializes it against the current arguments.
4. **Escape Analysis**: The compiler determines which objects are born and die within the scope of the partial evaluation. Objects that do not escape can be eliminated entirely.
5. **Residualization**: After all possible folding and specialization, the remaining AST is the residual program — a specialized version of the original.

```
Original AST          Partial Evaluation         Residual AST
┌─────────────┐      ┌──────────────────────┐    ┌──────────────┐
│ Config.get  │─────▶│ Constant-fold to 1   │    │              │
│ mode == 1?  │      │ Branch on constant   │───▶│ input * 2    │
│ input * 2   │      │ Eliminate else-branch│    │              │
└─────────────┘      └──────────────────────┘    └──────────────┘
```

### Truffle: Partial Evaluation as a Language Implementation Strategy

The most visible application of GraalVM's partial evaluation is the Truffle framework, which uses partial evaluation as the *primary* mechanism for implementing programming language interpreters. Truffle-based languages (including GraalPy, GraalJS, and Ruby/TruffleRuby) do not interpret source code line by line. Instead, they build ASTs for each statement and then *partially evaluate* those ASTs against the actual runtime inputs.

This means that a Truffle-based language implementation is not a traditional interpreter with optional JIT compilation. It is a *partial evaluator* that specializes a generic AST into optimized machine code on the fly. The language semantics are defined once in the AST, and partial evaluation does the rest.

This architectural choice has profound implications:

- **Self-optimizing**: The more a Truffle program runs, the more specialized its AST becomes, because partial evaluation peels away abstraction layers with each execution.
- **Polyglot interoperability**: Since all Truffle languages share the same partial evaluation engine, cross-language calls can be optimized across language boundaries. A call from JavaScript to Python is not a foreign function call — it is a partial evaluation of a specialized AST that knows the types and calling conventions of both sides.
- **Deoptimization safety**: Because partial evaluation maintains a precise correspondence between the AST and the runtime state, deoptimization (falling back to interpretation when assumptions are violated) is structurally sound and efficient.

### Partial Evaluation vs. Traditional JIT Compilation

It is worth drawing a clear architectural distinction between GraalVM's partial evaluation and conventional JIT approaches:

| Aspect | Traditional JIT (C2) | GraalVM Partial Evaluation |
|---|---|---|
| **Input** | Bytecode method | AST of method |
| **Optimization scope** | Method-level | Cross-method, recursive |
| **Constant propagation** | Local, within a method | Global, across call boundaries |
| **Dead code elimination** | Based on control flow | Based on partial evaluation residuals |
| **Deoptimization** | Bailout on assumption violation | Structural, based on AST residuals |
| **Language implementation** | Not designed for this | Primary mechanism (Truffle) |

The critical difference is that partial evaluation operates *recursively across method boundaries*. When it specializes a call site, it enters the callee's AST and specializes that too. This creates a compounding optimization effect that traditional JIT compilers achieve only through aggressive inlining — and even then, only within the inlining budget.

## Partial Evaluation in Practice: Native Image

GraalVM's Native Image compilation pipeline also leverages partial evaluation, though in a different form. During native image compilation, the entire application is analyzed ahead of time. The partial evaluator treats the application's static initialization and known class paths as constants, producing a native executable that contains only the code paths reachable from the entry points.

This is not the same as the runtime partial evaluation described above, but the intellectual lineage is identical. The key insight is the same: if you know something at compile time, fold it in and eliminate the rest.

In practice, this means Native Image produces binaries with:

- **No bytecode interpretation overhead**: The entire program is pre-specialized.
- **No garbage collection at runtime** (unless explicitly configured): Object lifetimes are determined at build time through escape analysis.
- **Fast startup**: No JIT warmup phase; the binary is already optimized.
- **Reduced memory footprint**: Dead code and unreachable class paths are stripped.

However, the tradeoff is that Native Image's partial evaluation operates under stricter constraints. Dynamic class loading, reflection, and runtime class generation are not visible to the build-time partial evaluator, requiring explicit configuration (such as reflection configuration files) to ensure that the residual program is correct.

```bash
# Example: Native Image compilation with reflection configuration
native-image --initialize-at-build-time \
  -H:ReflectionConfigurationFiles=reflect-config.json \
  -cp myapp.jar com.example.Main
```

## Patterns in Production

### When Partial Evaluation Shines

Partial evaluation delivers the most dramatic performance improvements in specific patterns:

1. **Configuration-heavy code**: Methods that read configuration values, feature flags, or environment settings and branch on them benefit enormously. The partial evaluator folds these into constants and eliminates entire code paths.

2. **Framework code with type-specialized hot paths**: Frameworks like Spring or Micronaut that use generics and reflection extensively can benefit when the GraalVM compiler specializes against concrete types. The framework's generic machinery becomes type-specific code at the hot path.

3. **Truffle-based language interpreters**: Any application that embeds a Truffle language (e.g., a rules engine or a scripting layer) gets the benefits of self-optimizing interpretation without manual JIT engineering.

4. **Recursive algorithms with known base cases**: Partial evaluation's recursive specialization naturally optimizes recursion when base cases are known at compile time.

### When It Adds Complexity

Partial evaluation is not a silver bullet. It introduces complexity in several areas:

- **Build-time constraints**: Native Image requires extensive configuration for dynamic features. The partial evaluator cannot see what it cannot see.
- **Deoptimization overhead**: When assumptions are violated at runtime (e.g., a class is loaded that the partial evaluator did not anticipate), deoptimization can be expensive.
- **Debugging difficulty**: The residual AST produced by partial evaluation bears little resemblance to the original source code, making stack traces and profiling harder to interpret.
- **Compilation time**: The recursive nature of partial evaluation means compilation can be slow for complex applications, particularly during the first few invocations when the AST is being built and specialized.

## Key Takeaways

- **Partial evaluation is not just an optimization — it is a compilation paradigm.** It transforms programs by specializing them against known constants, producing residual programs that are fundamentally different from the originals.
- **GraalVM's partial evaluation operates recursively across method boundaries**, achieving optimizations that traditional JIT compilers can only approximate through inlining.
- **Truffle uses partial evaluation as its core execution model**, not as an optional optimization pass. This makes Truffle-based languages self-optimizing by design.
- **Native Image applies partial evaluation at build time**, trading runtime flexibility for startup speed and memory efficiency.
- **The technique excels with configuration-heavy, type-specialized, and recursive code** but adds complexity for dynamic features like reflection and class loading.
- **Understanding partial evaluation changes how you think about JVM performance**, shifting focus from "how do I write JIT-friendly code" to "what constants can I make available to the compiler."

## Further Reading

- [GraalVM Documentation: Partial Evaluation](https://www.graalvm.org/latest/reference-manual/core/) — Official documentation covering the partial evaluation engine, Truffle framework, and Native Image compilation pipeline.
- [The GraalVM Compiler: Partial Evaluation and Truffle](https://www.graalvm.org/tutorials/partial-evaluation/) — A practical tutorial on building Truffle language implementations and understanding the partial evaluation loop.
- [Jones, Partial Evaluation and Automatic Program Generation (1979)](https://dl.acm.org/doi/10.1145/800227.806818) — The foundational paper by partial evaluation pioneer Neil D. Jones, which established the theoretical framework GraalVM builds upon.
- [GraalVM Native Image: A Practical Guide](https://www.graalvm.org/latest/reference-manual/native-image/) — Comprehensive guide to using Native Image for ahead-of-time compilation, including configuration for reflection, resources, and dynamic features.
- [Truffle Framework: A Framework for Building Language Interpreters](https://www.graalvm.org/tutorials/build-language-interpreter/) — Official tutorial for building a Truffle-based language interpreter from scratch, demonstrating partial evaluation in action.