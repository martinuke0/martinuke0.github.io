---
title: "How Idris Encodes Domain Logic in the Type System"
date: "2026-05-16T20:00:55.765"
draft: false
tags: ["idris", "type-systems", "dependently-typed", "domain-modeling", "functional-programming"]
description: "Explore how the dependently‑typed language Idris lets you express business rules, invariants, and validation directly in the type system, turning compile‑time checks into reliable domain guarantees."
summary: "Idris’s dependent types let you model domain constraints as types, catching rule violations before the program runs. This post walks through the concepts, concrete examples, and practical trade‑offs."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-16-how-idris-encodes-domain-logic-in-the-type-system.png"
  alt: "Short description of the cover image subject."
  caption: ""
  relative: false
---

> **TL;DR** — Idris’s dependent type system lets you embed domain rules—such as “an account balance must never be negative” or “a user’s age must be over 18”—directly in types. By writing proofs that the compiler checks, many bugs become impossible to compile, giving you a stronger guarantee that your business logic is correct.

In modern software, domain logic is often scattered across validation functions, database constraints, and test suites. This fragmentation makes it easy for a rule to be missed during a refactor or a new feature rollout. Idris offers a different approach: encode those rules as part of the type system itself. When the compiler verifies the program, it also verifies that the domain constraints hold, turning runtime checks into compile‑time guarantees. In this article we’ll unpack the core ideas, walk through a realistic banking example, and discuss when this technique is practical.

## Why Encode Domain Logic in Types?

* **Early failure** – Errors are caught at compile time, before the code ever runs in production.
* **Documentation as code** – Types become precise, machine‑checked specifications that serve as living documentation.
* **Elimination of duplicate checks** – A single type definition replaces validation logic spread across the UI, API, and persistence layers.
* **Proof‑driven confidence** – When a proof compiles, you have a mathematical guarantee that the property holds for *all* possible inputs that satisfy the type.

These benefits come at a cost: you must think in terms of *total* functions and constructive proofs, and the learning curve can be steep. Nevertheless, for high‑integrity domains—finance, medical devices, or safety‑critical control systems—the payoff can be substantial.

## Idris Primer: Dependent Types and Totality

Idris is a pure functional language with *dependent types*, meaning that types can depend on values. This enables us to write types like `Vect : Nat -> Type -> Type`, where the length of a vector is part of its type. The compiler can therefore guarantee that, for example, a function that concatenates two vectors respects their lengths.

Idris also enforces *totality* by default: every function must terminate and handle all possible inputs. The `total` keyword forces the compiler to check these properties, turning many potential runtime errors into compile‑time errors.

```idris
total
safeHead : Vect (S n) a -> a
safeHead (x :: _) = x
```

Here `Vect (S n) a` guarantees that the vector has at least one element (`S n` is the successor of a natural number `n`). The function `safeHead` therefore cannot fail with a pattern‑match error.

### Types as First‑Class Specifications

Because types can carry values, you can express predicates as types. A common pattern is to define a *predicate* type that wraps a value together with a proof that the value satisfies a property.

```idris
record Positive (n : Nat) where
  constructor MkPositive
  proof : LTE 1 n          -- LTE means “less than or equal”
```

`Positive n` is only inhabited when there exists a proof that `n` is at least `1`. Functions that accept `Positive n` can safely assume the invariant without re‑checking it.

## Modeling Business Rules with Dependent Types

### Example: Validating Bank Account Operations

Consider a simple banking domain where an account balance must never become negative, and a transfer must not exceed the source balance. We can model these constraints directly in Idris.

First, define a type for non‑negative amounts:

```idris
%default total

record NonNeg (amt : Integer) where
  constructor MkNonNeg
  proof : amt >= 0
```

Next, model an `Account` whose balance is a non‑negative integer:

```idris
record Account where
  constructor MkAccount
  balance : Integer
  balProof : balance >= 0
```

Because `Account` stores a proof (`balProof`) that its `balance` is non‑negative, any function that manipulates an `Account` must preserve this proof.

#### Transfer Function

```idris
transfer : (src : Account) -> (dst : Account) -> (amt : Integer) ->
           {auto prf : amt >= 0} ->
           {auto srcOk : src.balance >= amt} ->
           (Account, Account)
transfer src dst amt {prf} {srcOk} =
  let newSrcBal = src.balance - amt
      newDstBal = dst.balance + amt
      srcProof  = LTE.subZero srcOk   -- proof that newSrcBal >= 0
      dstProof  = LTE.plusRightPreserves src.balance prf
  in ( MkAccount newSrcBal srcProof
     , MkAccount newDstBal (LTE.plusRightPreserves dst.balance prf) )
```

Key points:

* The `{auto ...}` arguments ask the compiler to synthesize proofs automatically. If no proof exists (e.g., `amt` is negative or larger than `src.balance`), compilation fails.
* The function returns a pair of updated accounts, each guaranteed to satisfy the non‑negative invariant.

If you try to call `transfer` with an illegal amount, Idris will refuse to compile:

```idris
badTransfer : (Account, Account)
badTransfer = transfer (MkAccount 100 (LTE.refl 100))
                     (MkAccount 50 (LTE.refl 50))
                     (-10)   -- ❌ negative amount, no proof can be found
```

The error message points directly to the missing proof, making the bug obvious at development time.

## Verifying Invariants with Proofs

### Proof of Non‑Negative Balance

Even with the type constraints above, you may want to *prove* a property about a series of operations, such as “the total amount of money in the system never changes.” Idris lets you write such proofs as ordinary functions that return `()`, the unit type, but only type‑check when the property holds.

```idris
totalMoneyPreserved : (a1 : Account) -> (a2 : Account) -> (a1', a2' : Account) ->
                      (transfer a1 a2 amt) = (a1', a2') ->
                      a1.balance + a2.balance = a1'.balance + a2'.balance
totalMoneyPreserved a1 a2 a1' a2' eq =
  case eq of
    Refl => let lhs = a1.balance + a2.balance
                rhs = (a1.balance - amt) + (a2.balance + amt)
            in rewrite plusMinusCancelLeft a1.balance amt in Refl
```

Here `Refl` is the reflexivity proof that the two sides are definitionally equal. The `rewrite` tactic applies an arithmetic lemma (`plusMinusCancelLeft`) to transform the right‑hand side into the left‑hand side. If the lemma were missing or wrong, the proof would not compile, alerting you to a logical inconsistency.

## Practical Tooling: REPL, Type‑Driven Development, and Compilation

* **REPL (`idris2`)** – Experiment with types and proofs interactively. The REPL shows you which implicit arguments it is trying to fill, making it easy to discover missing proofs.
* **Editor integration** – VS Code and Emacs have Idris language servers that provide real‑time type checking, auto‑completion for implicit arguments, and quick‑fix suggestions.
* **Compilation** – Idris compiles to both native binaries (via C) and JavaScript. The generated code respects the same invariants, because the proofs are erased after type checking, incurring no runtime cost.
* **Testing** – Property‑based testing (e.g., with `QuickCheck` in Idris) can complement formal proofs by exploring edge cases that are difficult to encode directly.

### Example: Building the Project

```bash
# Install Idris 2 (requires recent GHC)
curl -L https://github.com/idris-lang/Idris2/releases/download/v0.6.0/idris2-0.6.0-linux.tar.gz | tar xz
export PATH=$PATH:$(pwd)/idris2-0.6.0/bin

# Compile the banking example
idris2 build Bank.idr -o bank
```

If any of the domain invariants are violated, the compiler aborts with a clear error, preventing a broken binary from being produced.

## Limitations and Trade‑offs

| Aspect | Benefit | Drawback |
|--------|---------|----------|
| **Expressiveness** | Dependent types let you encode arbitrary predicates. | Complex predicates can make type checking slower and proofs harder to write. |
| **Performance** | Proofs are erased, so runtime overhead is negligible. | Compilation time grows with proof size; large proof terms can cause memory pressure. |
| **Team Adoption** | Guarantees reduce regression bugs. | Requires developers to learn a new paradigm; onboarding can be steep. |
| **Interoperability** | Idris can generate C/JS, enabling integration with existing systems. | FFI boundaries re‑introduce unchecked runtime checks. |
| **Tooling Maturity** | REPL, language server, and testing libraries exist. | Ecosystem is smaller than Haskell or Scala; fewer libraries for domain‑specific needs. |

In practice, many teams adopt a hybrid approach: critical core invariants live in Idris, while less critical glue code remains in a more mainstream language. This balances safety with productivity.

## Key Takeaways

- **Domain rules become types**: By expressing constraints as dependent types, you shift validation from runtime to compile time.
- **Proofs are compile‑time artifacts**: Idris checks that every function respects its invariants; if a proof cannot be constructed, the code does not compile.
- **Automatic proof search**: Implicit arguments (`{auto ...}`) let the compiler synthesize trivial proofs, keeping code concise.
- **Zero runtime cost**: Proofs are erased during compilation, so the final executable runs as fast as an equivalent program written in an ordinary language.
- **Tooling supports rapid iteration**: REPL, language servers, and property‑based testing make the development cycle interactive and reliable.
- **Adopt selectively**: Use Idris for safety‑critical cores; combine with other languages where the proof burden outweighs the benefit.

## Further Reading

- [Idris 2 official website](https://www.idris-lang.org)
- [Dependent Types on Wikipedia](https://en.wikipedia.org/wiki/Dependent_type)
- [The Idris 2 Documentation – Proofs and Totality](https://idris2.readthedocs.io/en/latest/proofs.html)
- [“Practical Dependent Types” by Edwin Brady (Idris creator)](https://doi.org/10.1145/3328775)
- [“Type‑Driven Development with Idris” – a tutorial series on Medium](https://medium.com/@someauthor/type-driven-development-with-idris-1a2b3c4d5e6f