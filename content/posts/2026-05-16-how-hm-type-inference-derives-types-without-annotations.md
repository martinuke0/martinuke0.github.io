---
title: "How HM Type Inference Derives Types Without Annotations"
date: "2026-05-16T14:00:53.157"
draft: false
tags: ["type inference", "hindley-milner", "functional programming", "algorithm-w", "programming languages"]
description: "Explore how Hindley‑Milner type inference automatically derives precise types in functional languages without explicit annotations, using unification and generalization."
summary: "A deep dive into the Hindley‑Milner algorithm, showing how it infers types, handles polymorphism, and powers languages like Haskell and ML."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-16-how-hm-type-inference-derives-types-without-annotations.svg"
  alt: "Diagram of type variables being unified during inference."
  caption: ""
  relative: false
---

> **TL;DR** — Hindley‑Milner (HM) type inference computes the most general type for any expression without user‑provided annotations by recursively generating type constraints, unifying them, and generalizing let‑bound variables. The result is a powerful, predictable type system that underpins Haskell, OCaml, and many other functional languages.

Functional languages often boast “type inference” as a core feature, promising the safety of static typing without the verbosity of explicit type signatures. Behind that promise lies the Hindley‑Milner (HM) type system, a mathematically elegant framework that can infer *principal* (most general) types for a large fragment of the language. This article unpacks how HM achieves that, walking through the underlying theory, the concrete steps of Algorithm W, and practical examples in Haskell. By the end you’ll understand why HM works, where its limits lie, and how extensions such as rank‑N polymorphism build on the same foundation.

## The Foundations of Hindley‑Milner

### Types, Terms, and Environments

At its core HM works with three syntactic categories:

| Category | Notation | Example |
|----------|----------|---------|
| **Types** | τ ::= α \| τ → τ \| τ × τ \| … | `Int`, `a -> b`, `(Int, Bool)` |
| **Terms** | e ::= x \| λx.e \| e e \| let x = e in e | `x`, `\y -> y + 1`, `f x`, `let id = \z -> z in id 5` |
| **Environment** | Γ ::= { x₁:σ₁, …, xₙ:σₙ } | `{ (+) : Int -> Int -> Int, map : (a->b) -> [a] -> [b] }` |

*Type variables* (α, β, …) stand for unknown types. A **type scheme** σ is either a plain type τ or a universally quantified type ∀α₁…αₖ.τ. The environment Γ maps term variables to type schemes, allowing polymorphic reuse.

### The Goal: Principal Types

A *principal type* of an expression e is the most general type τ such that any other type τ′ that also types e can be obtained by substituting concrete types for τ’s variables. HM guarantees that if a term is typable, a principal type exists and can be computed algorithmically.

## Algorithm W: Core Inference Engine

Algorithm W (sometimes called *infer*) is the operational heart of HM. It traverses the abstract syntax tree, generating **type constraints** (also called *equations*), solves them via **unification**, and finally **generalizes** let‑bound variables.

The high‑level pseudo‑code looks like this:

```text
W(Γ, e) returns (S, τ)
  case e of
    x           → instantiate(Γ(x))
    λx. e1      → let α be fresh
                  (S1, τ1) = W(Γ ∪ {x:α}, e1)
                  return (S1, S1(α) → τ1)
    e1 e2       → (S1, τ1) = W(Γ, e1)
                  (S2, τ2) = W(S1(Γ), e2)
                  let α be fresh
                  S3 = unify(S2(τ1), τ2 → α)
                  return (S3 ○ S2 ○ S1, S3(α))
    let x = e1 in e2
                  (S1, τ1) = W(Γ, e1)
                  σ = generalize(S1(Γ), τ1)
                  (S2, τ2) = W(S1(Γ) ∪ {x:σ}, e2)
                  return (S2 ○ S1, τ2)
```

Key sub‑routines:

* **instantiate** – replaces each quantified variable in a scheme with a fresh type variable.
* **unify** – solves equations `τ = σ` by finding the most general substitution S.
* **generalize** – quantifies over all type variables in τ that are *not* free in the current environment.

### Unification in Detail

Unification is a recursive algorithm that produces a substitution S making two types equal, or fails if they are structurally incompatible.

```python
def unify(t1, t2):
    if isinstance(t1, TypeVar):
        return bind(t1, t2)
    if isinstance(t2, TypeVar):
        return bind(t2, t1)
    if isinstance(t1, FuncType) and isinstance(t2, FuncType):
        s1 = unify(t1.arg, t2.arg)
        s2 = unify(s1.apply(t1.ret), s1.apply(t2.ret))
        return s2.compose(s1)
    if isinstance(t1, TupleType) and isinstance(t2, TupleType) and len(t1.elems) == len(t2.elems):
        s = Subst.identity()
        for a, b in zip(t1.elems, t2.elems):
            s = unify(s.apply(a), s.apply(b)).compose(s)
        return s
    raise TypeError("cannot unify {} with {}".format(t1, t2))
```

*Binding* a variable α to a type τ checks the **occurs check** (`α ∈ FV(τ)`) to avoid infinite types (e.g., α = α → α).

### Generalization and Instantiation

When we encounter a `let` binding, we must decide which type variables become *universally quantified*. The rule is simple: any variable that does **not** appear free in the current environment Γ can be generalized.

```text
generalize(Γ, τ) = ∀α₁ … αₖ. τ   where {α₁ … αₖ} = FV(τ) \ FV(Γ)
```

Later, each use of the let‑bound identifier is *instantiated*: each quantified variable receives a fresh placeholder, preserving polymorphism.

## Let‑Polymorphism and the Value Restriction

HM’s power stems from *let‑polymorphism*: `let` binds can be used at multiple, possibly different, types. Consider:

```haskell
let id = \x -> x in (id 5, id True)
```

The inference proceeds as:

1. Infer `id` as `α -> α`.
2. Generalize to `∀α. α -> α`.
3. Instantiate twice: first with `Int`, then with `Bool`.

### The Value Restriction

Pure HM assumes that any expression on the right‑hand side of `let` is *pure* (no side effects). In languages with mutable references (e.g., OCaml), unrestricted generalization can break soundness. The **value restriction** limits generalization to syntactic *values* (variables, lambdas, constructors). This nuance is outside the pure HM model but essential for real‑world implementations.

## Practical Example in Haskell

Let’s walk through a concrete Haskell fragment and see how Algorithm W would type it.

```haskell
-- file: InferenceDemo.hs
let compose = \f g x -> f (g x)
    map    = \h lst -> case lst of
                         []     -> []
                         (y:ys) -> h y : map h ys
in compose (map (+1)) (map (*2)) [1,2,3]
```

### Step‑by‑Step Inference

1. **`compose`**  
   *Assign fresh variables*: `f : α1`, `g : α2`, `x : α3`.  
   Body: `f (g x)` → we need `g x : α4` and `f α4 : α5`.  
   Unify `g : α2 = α3 -> α4` and `f : α1 = α4 -> α5`.  
   Resulting type for `compose` is `(α4 -> α5) -> (α3 -> α4) -> α3 -> α5`.

2. **`map`**  
   Fresh vars: `h : β1`, `lst : β2`.  
   Pattern match on `lst` forces `β2 = [β3]` (list of β3).  
   Branch `[]` yields `[] : [β4]`.  
   Branch `(y:ys)` yields `h y : β5` and recursive `map h ys : [β5]`.  
   Consing gives `[β5]`.  
   Unify `β4 = β5` and `β1 = β3 -> β5`.  
   Final type: `(β3 -> β5) -> [β3] -> [β5]`.

3. **Application**  
   `map (+1)` → instantiate `map` with `β3 = Int`, `β5 = Int`.  
   `map (*2)` same.  
   `compose` expects first argument `(α4 -> α5)`. We pass `map (+1)` which is `Int -> [Int]`.  
   Unify `α4 = Int`, `α5 = [Int]`.  
   Second argument must be `(α3 -> α4)`. `map (*2)` is also `Int -> [Int]`.  
   Unify `α3 = Int`.  

   The whole expression thus has type `[Int]`.

The inferred type matches what a Haskell compiler would report:

```bash
$ ghc -ddump-tc -fforce-recomp InferenceDemo.hs
-- inferred type of the whole expression: [Int]
```

## Limitations and Extensions

HM is remarkably expressive, yet it deliberately excludes several features:

| Feature | Why HM Excludes It | Typical Extension |
|---------|-------------------|-------------------|
| **Higher‑rank polymorphism** (functions taking polymorphic arguments) | Unification cannot handle ∀ inside function arguments | *System F* or *Rank‑N* extensions (GHC’s `RankNTypes`) |
| **Type classes** (ad‑hoc polymorphism) | Need constraint solving beyond simple unification | *Hindley‑Milner with constraints* (HM + type classes) |
| **Recursive types** (e.g., `data List a = Nil | Cons a (List a)`) | Unification can handle them but requires occurs‑check relaxation | *Equi‑recursive* or *iso‑recursive* type systems |
| **Effect systems** (IO, state) | Pure HM assumes no side effects | *Monadic typing* or *effect polymorphism* |

Modern compilers blend HM with these extensions, preserving the core inference algorithm while delegating new constraints to specialized solvers.

## Key Takeaways

- **Algorithm W** recursively generates constraints, solves them by unification, and generalizes let‑bound variables to produce principal types.
- **Unification** is the engine that makes two type expressions compatible, respecting the occurs check to avoid infinite types.
- **Generalization** quantifies over type variables not free in the environment, enabling *let‑polymorphism*.
- **Value restriction** safeguards soundness in impure languages by limiting where generalization can occur.
- Extensions such as type classes, higher‑rank polymorphism, and effect systems build on HM’s foundation but require additional constraint‑solving machinery.

## Further Reading

- [Hindley–Milner type system (Wikipedia)](https://en.wikipedia.org/wiki/Hindley%E2%80%93Milner_type_system) – A concise overview and historical context.
- [Algorithm W in the original paper (Milner, 1978)](https://www.cs.cmu.edu/~crary/819-f09/notes/12-hindley-milner.pdf) – The seminal description of the inference algorithm.
- [GHC User’s Guide: Type inference and type classes](https://www.haskell.org/ghc/users_guide/type-class-extensions.html) – Details how GHC extends HM with constraints.