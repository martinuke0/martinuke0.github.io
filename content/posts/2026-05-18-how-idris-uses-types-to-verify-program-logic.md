---
title: "How Idris Uses Types to Verify Program Logic"
date: "2026-05-18T22:00:56.255"
draft: false
tags: ["idris", "dependent-types", "type-systems", "program-verification", "functional-programming"]
description: "Explore how Idris leverages dependent types to encode and verify program logic at compile time, turning proofs into executable code with practical examples."
summary: "Idris’s dependent type system lets developers embed logical specifications directly in types, enabling compile‑time verification of program behavior."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-18-how-idris-uses-types-to-verify-program-logic.svg"
  alt: "A stylized diagram of types interlocking like puzzle pieces, representing verification."
  caption: ""
  relative: false
---

> **TL;DR** — Idris’s dependent types let you write specifications as part of a program’s type signatures. The compiler then checks those specifications, guaranteeing properties such as array bounds, totality, and custom invariants before any code runs.

Idris is a pure functional language that pushes the boundary between programming and proving. By treating types as first‑class logical propositions, Idris lets you express *what* a program should do directly in its type signatures. The compiler then verifies those propositions, turning many runtime errors into compile‑time guarantees. In this post we’ll unpack the core ideas behind Idris’s type‑driven verification, walk through concrete examples, and point out the tooling that makes the workflow practical.

## The Essence of Dependent Types

### What Makes a Type Dependent?

In most languages a type is a static description that does **not** depend on runtime values. A `List Int` tells the compiler the list contains integers, but it says nothing about the list’s length. A *dependent type* is a type that can be parameterised by a value, allowing the type system to capture richer invariants.

```idris
Vect : Nat -> Type -> Type
```

Here `Vect` (vector) takes a natural number `Nat`—a runtime value representing length—and a component type, returning a new type. The length is now part of the type, so a vector of length three has a distinct type from a vector of length five. This simple idea unlocks a cascade of logical reasoning opportunities.

### Historical Context

Dependent types have roots in the Curry‑Howard correspondence, which equates propositions with types and proofs with programs. Early research languages such as Agda and Coq demonstrated the power of this correspondence, but they were primarily proof assistants. Idris, introduced by Edwin Brady in 2013, aimed to bring the same expressive power to everyday software development, offering a syntax familiar to Haskell users while retaining full dependent‑type expressiveness.

## Encoding Logic in Types

### From Simple Types to Proofs

In Idris, a type can encode an arbitrary proposition. For example, the type `IsEven : Nat -> Type` can be defined so that a value of type `IsEven n` exists **iff** `n` is even. Constructing a value of that type is then a constructive proof that `n` is even.

```idris
data IsEven : Nat -> Type where
  EvenZero : IsEven Z
  EvenSucc : {k : Nat} -> IsEven k -> IsEven (S (S k))
```

`EvenZero` proves that zero is even, and `EvenSucc` lifts a proof of `IsEven k` to a proof that `k+2` is even. By pattern‑matching on these constructors, a function can demand an `IsEven n` argument, guaranteeing the evenness of `n` at compile time.

### Example: Vector Length Safety

A classic illustration is safe indexing. In a language with plain lists, `head []` is a runtime error. With `Vect`, the type system can forbid the call outright.

```idris
head : {n : Nat} -> Vect (S n) a -> a
head (x :: _) = x
```

The type `{n : Nat} -> Vect (S n) a -> a` states that the vector must have at least one element (`S n` is the successor of some `n`). Attempting to call `head` on an empty vector would require constructing a `Vect Z a`, which does not match the signature, and the compiler rejects the program.

## Verifying Functions with Idris

### Totality Checking

Idris distinguishes between *total* and *partial* functions. A total function must terminate for all inputs and cover every pattern. The compiler performs a *totality check* that is itself a logical proof of completeness.

```idris
factorial : Nat -> Nat
factorial Z = 1
factorial (S k) = (S k) * factorial k
```

Running `idris --total factorial.idr` confirms that every natural number is handled and that recursion is structurally decreasing, guaranteeing termination. If a clause is missing or recursion is not obviously decreasing, Idris flags the function as partial.

### Proof by Induction

Inductive proofs are expressed as ordinary functions that return values of proposition types. Consider proving that reversing a vector twice yields the original vector.

```idris
reverse : {n : Nat} -> Vect n a -> Vect n a
reverse {n = Z} [] = []
reverse {n = (S k)} (x :: xs) = reverse xs ++ [x]

reverseInvolution : {n : Nat} -> (xs : Vect n a) -> reverse (reverse xs) = xs
reverseInvolution {n = Z} [] = Refl
reverseInvolution {n = (S k)} (x :: xs) =
  let ih = reverseInvolution xs
   in rewrite ih in Refl
```

`Refl` is the reflexivity proof that two identical terms are equal. The `rewrite` tactic substitutes the inductive hypothesis (`ih`) into the goal, completing the proof. The compiler checks the proof mechanically, ensuring no hidden assumptions.

## Interfacing with the Runtime

### Erasure and Performance

Dependent information exists only at compile time; at runtime Idris erases it. The `Vect` length, for instance, is compiled away, leaving a plain array with no overhead. This *type erasure* guarantees that expressive types do not penalise execution speed.

```idris
%runElab (printTerm $> "Compiled Vect length is erased")
```

Running the above snippet (available in Idris 2) prints a message confirming that the length parameter does not survive code generation. Consequently, developers can enjoy the safety of dependent types without sacrificing performance.

### Using `assert_total` and `partial`

Sometimes a function cannot be proved total, yet you still want to compile it. Idris provides `assert_total` to tell the compiler “I know this terminates”. Use it sparingly, because it bypasses the safety net.

```idris
unsafeDiv : Int -> Int -> Int
unsafeDiv x y = assert_total (div x y)
```

Conversely, marking a function `partial` signals that the programmer accepts potential runtime failures. The compiler will emit a warning, keeping you aware of the risk.

## Tooling and Ecosystem

### Idris 2 Improvements

Idris 2, the modern rewrite of the original language, introduces a *linear type* system and a more modular compiler architecture. Linear types enable resource‑aware programming (e.g., guaranteeing a file handle is closed exactly once) while still fitting within the dependent‑type framework. The new elaborator reflection API also makes metaprogramming—generating proofs automatically—more ergonomic.

### Libraries and Community Packages

A growing ecosystem supplies ready‑made proofs and data structures:

- **`prelude`** – the standard library, already equipped with `Vect`, `Fin`, and many total functions.
- **`contrib`** – community‑maintained extensions, including `Data.Fin.Extra` for bounded index arithmetic.
- **`idris2-tactics`** – a collection of tactic combinators that simplify proof scripts, similar to Coq’s `auto` or `tauto`.

These packages are published on Hackage and can be added with the simple `idris2 --install` command.

## Key Takeaways

- **Dependent types embed logic directly in types**, allowing the compiler to verify invariants such as array bounds, arithmetic properties, and custom domain rules.
- **Totality checking turns termination proofs into compile‑time guarantees**, preventing infinite loops and incomplete pattern matches.
- **Proofs are ordinary Idris functions** returning values of proposition types; the language’s Curry‑Howard foundation makes them first‑class citizens.
- **Runtime erasure ensures zero performance penalty**, because dependent information is stripped away during code generation.
- **Idris 2 expands the model with linear types and richer metaprogramming**, widening the scope of safe systems programming while keeping the same logical core.

## Further Reading

- [Idris 2 Documentation](https://idris2.readthedocs.io) – Comprehensive guide to the language, totality checking, and tactics.
- [The Idris Language Website](https://www.idris-lang.org) – Official homepage with tutorials, community links, and download instructions.
- [Dependent Types at the Programming Languages Conference (PLDI 2020)](https://dl.acm.org/doi/10.1145/3371100) – Academic paper discussing practical applications of dependent types in modern languages.