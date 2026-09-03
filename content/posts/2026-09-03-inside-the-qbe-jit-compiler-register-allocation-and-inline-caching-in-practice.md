---
title: "Inside the QBE JIT compiler: register allocation and inline caching in practice"
date: "2026-09-03T18:01:00.747"
draft: false
tags: ["compilers", "jit", "qbe", "register-allocation", "inline-caching", "systems"]
description: "A practitioner's walkthrough of QBE's register allocator and inline caching strategies, with patterns you can borrow for your own JIT."
summary: "How QBE compiles SSA IR to machine code, with a close look at its linear-scan register allocator and the inline caching techniques production JITs use to recover lost megamorphic performance."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-inside-the-qbe-jit-compiler-register-allocation-and-inline-caching-in-practice.svg"
  alt: "Abstract representation of compiler IR flowing into a register grid."
  caption: ""
  relative: false
---

> **TL;DR** — QBE's backend is a compact, four-pass pipeline that turns typed SSA IR into native code, anchored by a linear-scan register allocator that trades a little spill quality for predictable speed. Production JITs pair that allocator-style approach with inline caches to recover megamorphic dispatch, and the same combination is achievable on top of QBE with surprisingly little code.

## Why QBE is worth a second look

Most blog posts about JIT internals reach for V8, HotSpot, or LuaJIT because those are the engines people have actually shipped at scale. That's reasonable, but those codebases are also millions of lines of C++, guarded by corporate lawyers, and only readable in the abstract. If you want to *see* what a real backend looks like — register allocation, calling conventions, spilling, machine code emission — there is almost no better starting point than [QBE](https://c9x.me/compile/), the 10k-line compiler backend by Quentin Carbonneaux.

QBE is not a JIT in the conventional sense. It is an SSA-based, target-aware backend that consumes a small typed IR and emits object code for x86_64, arm64, and rv64. But its simplicity is exactly the point: it is the cleanest open-source example of the same algorithms that production JITs run, shorn of the historical layers and vendor-specific workarounds. If you have ever wanted to read a backend and actually finish the read, this is the one.

The other reason QBE is interesting today is that a small but growing set of language runtimes are now using it inside a JIT loop. Pony has experimented with QBE for tracing, and [the Gluon frontend](https://github.com/bobrik/gluon) uses QBE as a backing compiler for a dynamically typed functional language. In those projects, register allocation is the bottleneck, and inline caching is the technique that makes the generated code competitive with hand-tuned interpreters.

This post walks through what QBE actually does on the register-allocation side, then zooms out to the inline-caching strategies those QBE-fronted JITs use to handle polymorphic call sites.

## The QBE pipeline at a glance

QBE's design is famously small. From `parse.c` to `emit.c`, it is roughly four major passes, all of which fit in your head:

1. **Parse and typecheck.** The frontend reads the textual IL and resolves temporaries into a flat, typed value list. There is no symbol table beyond a per-function array of temporaries.
2. **Mem2reg.** A textbook copy-of-phi elimination pass that promotes allocas out of SSA so most values live in registers or spill slots for their entire lifetime.
3. **Copy simplification and liveness.** QBE folds trivial copies, builds a single chain of parallel moves per block, and computes live ranges using a worklist-driven backward dataflow pass.
4. **Register allocation and emission.** A linear-scan walk over live intervals, with spilling and reload insertion folded into the same pass that emits machine code.

The output is object code, not assembly — QBE has its own x86_64 and arm64 encoders that hand-pack instructions rather than shelling out to `as`. That decision matters for our purposes: it means the register allocator and the emitter are *the same* pass, so we can talk about them together.

## Linear-scan register allocation, the QBE way

Linear-scan allocation was introduced by [Poletto and Sarkar in 1999](https://www.cs.princeton.edu/~mps/popl99.pdf) and is now standard fare. The idea is simple: instead of building an explicit interference graph and colouring it NP-hard style, walk the program in order and keep an "active" set of live ranges whose start point has been seen but whose end point hasn't. Whenever a new range starts, expire any active ranges that have ended, then either allocate a free register or spill the worst candidate.

The trade-off is that linear-scan gives up some quality for predictability. On x86_64 with 16 general-purpose registers it produces code within a few percent of graph colouring for almost all real programs, and it does so in roughly linear time rather than cubic. QBE goes one step further: it does not maintain a fully ordered active set. It uses a simple linear search through a small fixed-size array (often called "the bucket" in the source), which is fine because register counts on real architectures are tiny.

### Live ranges, not intervals

A subtle but important detail: QBE computes **liveness**, not intervals. A live range is the contiguous span of program points where a value is potentially read before being written. Linear-scan algorithms work on intervals, but real programs have lifetimes that fork and rejoin in the control-flow graph. The simplest fix is to break a live range into per-basic-block segments — a fresh segment at every definition or join — and treat each segment independently. This is what QBE does, and it is the source of almost every "why did my value get spilled twice?" question you will ever ask on the mailing list.

The practical consequence is that a value defined in a loop and used outside it has *two* ranges in the eyes of the allocator: one inside the loop and one from the loop exit to the final use. The two ranges do not get the same register, which means QBE will insert a copy at the loop edge. On hot loops this can be costly. The workaround in QBE-fronted JITs is to mark loop-carried values as `@slot` in the IR — telling the backend they live in a fixed stack location — so that the copies collapse to nothing.

### The allocation pass

The relevant source lives in `rega.c` and is structured as a small state machine:

```text
for each instruction, in order:
    for each use operand:
        if it expires at this point: free its register
        if it has a hint, try to allocate to the hint
        allocate or spill
    emit parallel copy chain for the instruction's defs
    emit the instruction itself
```

Three details are worth pulling out.

First, **hinting**. Each value can carry an optional hint operand that suggests which register to prefer. QBE's frontend exploits this aggressively. For example, the divide-by-constant sequence emitted for power-of-two divisors hints the magic-number multiplier into `rax` so the actual division can use the 2-operand form. Without the hint, the linear scan has no way to know that the multiply is special.

Second, **spilling**. When the active set is full and a new range needs a register, QBE picks a victim based on a small heuristic: ranges whose endpoints are furthest away are evicted first, with a tiebreaker that prefers spills for values already in memory. This is a much cruder model than graph colouring's priority queue, but in practice it works because the IR is already simplified and the allocator's working set is tiny.

Third, **parallel moves**. QBE emits each basic block's phi-resolving moves as a single parallel-move sequence, which it then lowers to a sorted series of swaps. This avoids the well-known temporaries-needed-for-naive-cycles problem and is the same trick used in [LLVM's register allocator](https://llvm.org/docs/CodeGeneration.html#the-register-allocator).

### What this looks like for a tight loop

Consider a numeric inner loop that accumulates a sum across an array:

```text
@sum =l phi @start, @sum_next
@i   =l phi 0, @i_next
@i_next =l add @i, 1
@v   =w loadw @base + @i
@sum_next =l add @sum, @v
branch @i_next < @n ? loop : done
```

After mem2reg there are no allocas; everything is in SSA. The liveness pass will produce roughly two short ranges per value (one inside the loop, one bridging the exit), so the allocator will pick *some* register for the in-loop values and *some* register for the back-edge copies, and insert a parallel move at the top of the loop body. On a 16-register machine you will see no spills. On a 6-register machine you might see one. The point is that the same algorithm runs identically across both targets, which is what makes QBE pleasant to port.

## Inline caching, and why QBE backends need it

Register allocation is half of the story. The other half is what happens at *call sites* — specifically, calls to user-defined functions whose target and argument types are not known at compile time. A pure QBE backend, naively compiled, will emit a vanilla `call` instruction for every dynamic call, which is a cache miss every time. Production JITs do better, and the technique they use is called an **inline cache**.

The concept is older than most engineers realise. [Deutsch and Schiffman](https://dl.acm.org/doi/10.1145/800055.802030) introduced inline caches for Smalltalk in 1984. The basic recipe is:

1. At the call site, speculatively stash a (class, target) pair in a small fixed-size cache line embedded next to the call instruction.
2. On entry, check that the receiver's class matches the cached one. If yes, jump directly to the cached target with no further dispatch.
3. If no, fall through to a slow path that re-resolves the call, updates the cache, and resumes execution.

Inline caches come in three flavours, and a good JIT has all three:

- **Monomorphic.** One observed (class, target). Hit rate of ~99% on production workloads.
- **Polymorphic.** A small fixed-size array of (class, target) entries, checked with a binary search tree. Hit rates of 90–95% even on polymorphic sites.
- **Megamorphic.** The site has seen too many classes; the cache is degraded to a hash lookup or a pointer-chase through a hidden-class chain. Hit rates drop into the 70s.

The magic is that *all three* can be implemented in roughly 30 lines of generated code per call site. QBE's IR is well-suited to this because every call site already gets its own basic block and its own set of temporaries, so you can stitch the cache state into the function's prologue without disturbing the rest of the IR.

### A minimal inline cache in QBE IL

Here is what a monomorphic inline cache for a single-argument call might look like in QBE IL:

```text
export function @call_site (%p, %cls, %recv) {
    @st =l phi %st_start, %st_next
    @cache_class =l loadl @st
    @eq =w ceql @cache_class, %cls
    jnz @eq, @hit, @miss

@hit:
    @target =l loadl @st + 8
    @r =l call @target(%recv)
    jmp @cont

@miss:
    @r =l call @resolve(%st, %cls, %recv)
    @st_next =l @r ?? %st
    jmp @cont

@cont:
    ...
}
```

The trick is that `%st` is a per-call-site allocation in the JIT's heap, not on the QBE side's stack. The two loads and the compare are essentially free on modern x86 — they fold into the front-end of the pipeline — and the fast path takes 3–4 instructions with no branches into the allocator's slow path. On a megamorphic site, the cache line grows to a small hash table and the JIT replaces the equality test with a probe; the rest of the generated function is unchanged.

### Why this works so well

Inline caches are not magic, but they exploit three hard facts about production object programs:

- **Objects are stable.** In any non-trivial program, the vast majority of call sites see the same class for the same call site across the program's lifetime. This is Deutsch and Schiffman's original observation.
- **Class checks are cheap.** A pointer load and an integer compare is essentially free relative to the cost of a generic dispatch.
- **Failure is rare.** When a cache misses, we have already burned tens of cycles to set up the call. Spending a few hundred more on a real dispatch is fine.

The interesting design question is *where* to draw the line between polymorphic and megamorphic. Most production JITs use a small threshold (often 4 or 8 entries) before downgrading the cache to a hash lookup, on the theory that more entries hurt the hot path more than they help. [The V8 inline cache design](https://v8.dev/blog/inline-caches) is a good reference, and so is the [Hidden Classes paper from Boost.Conference](https://www.youtube.com/watch?v=Udi6DVlciYY).

## Patterns in production: Gluon and friends

Gluon, a small dynamically typed functional language by Bobrik, is probably the closest you will get to a "real" production JIT that ships on top of QBE. It compiles a Lisp-like surface syntax into QBE IL, then runs the resulting object code through QBE's backend. Because the language is dynamically typed, almost every operation is a potential call site, and inline caches are the difference between "toy interpreter" and "actually usable language".

The pattern Gluon uses is instructive:

1. **Front-end lowering.** Every syntactic call becomes a special `call_dynamic` runtime primitive. The primitive takes a function value, an argument count, and a hidden-class id from each argument.
2. **Per-site cache.** The runtime allocates a small cache struct at first invocation. Subsequent calls find the struct via a pointer stashed in the call site's own prologue block.
3. **Hidden classes** rather than nominal classes. When a value flows through a polymorphic site, the JIT builds a hidden class on the fly (essentially a structural type) and compares hidden-class ids rather than nominal class pointers. This is the same trick [V8 uses](https://v8.dev/blog/fast-properties) and is essential when the language has no static class hierarchy.
4. **Megamorphic demotion.** After a threshold of distinct hidden classes is observed at a site, the runtime swaps the cache struct for a hash table. The fast path checks the same prologue block but falls into a probe-and-jump sequence instead of a single compare.

The result, in Gluon's case, is that simple programs run about 5–10x slower than equivalent C, which is roughly the same ballpark as CPython on the same workloads. That is not going to win any benchmarks, but it is the right order of magnitude for a JIT that fits in a single C file.

### How QBE's allocator helps

The most underappreciated feature of QBE for JITs is that the **allocator does not care** whether the program is dynamically typed. As far as `rega.c` is concerned, every value is a typed temporary with a definite lifetime. The dynamic typing lives in the runtime, in the form of tagged values and hidden-class ids, but the IR stays statically typed. This is the same separation that V8 uses — the type feedback lives in side tables, the IR stays clean — and it is the single biggest reason a tiny backend can support a JIT at all.

A nice corollary is that the **same IR optimisation passes** keep working regardless of how polymorphic the call sites are. Inlining, copy folding, dead-code elimination all run on the SSA form and never need to peek into the cache state. The cache is purely a runtime concern, woven into the call site's emitted code, but invisible to the allocator.

## Practical advice if you are building a JIT on top

A few rules of thumb for anyone writing a small JIT that lowers to QBE or a similar SSA backend:

- **Keep live ranges short.** SSA's phi nodes and parallel moves can fool the allocator into splitting a range across the loop edge. Use `@slot` annotations for any value that needs to survive across a back-edge.
- **Use hints.** A two-operand instruction that wants a specific register is a missed opportunity if you let the allocator pick freely. QBE's hint mechanism is cheap to add at the IR-generation step.
- **Inline cache every dynamic call site.** The cost on the fast path is one or two extra instructions. The cost on the slow path is bounded by your dispatch mechanism.
- **Demote to megamorphic early.** A four-entry polymorphic cache covers almost all real call sites. Anything beyond that is generally noise.
- **Measure, don't guess.** Inline caches are sensitive to object lifetimes in a way that is hard to predict. Profile a representative workload before tuning the demotion threshold.

If you are not building a JIT yourself, the same patterns apply to language interpreters that want to fall back to compiled code, and to VM dispatch loops that want to avoid a global interpreter lock. The shape is the same: identify the hot path, speculatively cache the result, fall back to a slow path on miss.

## Key Takeaways

- QBE's backend is a four-pass pipeline whose register allocator is a small linear scan, hint-driven, and tightly integrated with machine-code emission.
- Live-range splitting at loop edges is the most common source of avoidable copies in QBE-emitted code; `@slot` annotations are the standard workaround.
- Inline caches convert megamorphic dynamic dispatch into a 3–4-instruction fast path; without them, a QBE-backed JIT is too slow to be usable.
- Hidden classes, not nominal classes, are the right comparison key for dynamically typed languages and integrate cleanly with QBE's typed IR.
- The QBE architecture cleanly separates IR optimisation (allocator-friendly) from runtime feedback (cache state), which is why small backends can host production-quality JITs.

## Further Reading

- [QBE — Quentin Carbonneaux's compiler backend](https://c9x.me/compile/)
- [Gluon — a small functional language using QBE](https://github.com/bobrik/gluon)
- [Linear Scan Register Allocation — Poletto and Sarkar, POPL 1999](https://www.cs.princeton.edu/~mps/popl99.pdf)
- [Efficient Implementation of the Smalltalk-80 System — Deutsch and Schiffman, POPL 1984](https://dl.acm.org/doi/10.1145/800055.802030)
- [V8's inline caching design notes](https://v8.dev/blog/inline-caches)
- [LLVM's CodeGeneration documentation, including register allocation overview](https://llvm.org/docs/CodeGeneration.html#the-register-allocator)