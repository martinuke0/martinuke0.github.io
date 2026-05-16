---
title: "Implementing Formal Verification for Critical Rust Memory Safety Transitions"
date: "2026-05-16T00:00:24.312"
draft: false
tags: ["rust", "formal verification", "memory safety", "model checking", "proof assistants"]
description: "Learn how to apply formal verification to Rust's critical memory‑safety transitions, using model checking, proof assistants, and tooling to guarantee safety."
summary: "A step‑by‑step guide to integrating formal verification into Rust projects, focusing on memory‑safety transitions and practical toolchains."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-16-implementing-formal-verification-for-critical-rust-memory-safety-transitions.svg"
  alt: "Illustration of a Rust program with formal verification symbols overlayed."
  caption: ""
  relative: false
---

> **TL;DR** — Formal verification can close the safety gaps that even Rust’s borrow checker leaves open. By combining model‑checking tools like Prusti with proof assistants such as Coq, you can mathematically guarantee that critical memory‑safety transitions in production code are free from undefined behavior.

Rust’s ownership model eliminates most classes of memory bugs, yet certain low‑level transitions—unsafe blocks, FFI boundaries, and hardware‑specific drivers—still require extra assurance. This post walks through the theory, tooling, and concrete workflow needed to bring formal verification to those high‑risk areas, helping you ship Rust code that is provably safe.

## Why Formal Verification Matters for Rust Memory Safety

### The Limits of the Borrow Checker

The borrow checker enforces *lexical* lifetimes, but it cannot reason about:

- **Dynamic invariants** that depend on runtime state (e.g., “a pointer is never dereferenced after a peripheral reset”).
- **Unsafe contracts** exposed by `unsafe fn` signatures.
- **FFI interactions** where the external library’s guarantees are not encoded in Rust types.

These gaps are documented in the Rustonomicon and have led to real bugs. For example, the [RingBuf race condition in the `tokio` runtime](https://github.com/tokio-rs/tokio/issues/3228) surfaced because the borrow checker could not express the ordering constraints across threads.

### Real‑World Incidents

| Project | Issue | Root Cause |
|---------|-------|------------|
| `serde_json` | Use‑after‑free in custom deserializer | Unsafe pointer arithmetic in a helper function |
| `hyper` | Memory leak when TLS stream is abruptly closed | Missing invariant about socket state transition |
| Embedded driver for STM32 | Hard‑fault after DMA re‑configuration | Incorrect assumption about buffer lifetime across ISR |

These incidents illustrate why a *formal* guarantee—proof that a property holds for all possible executions—is valuable even in a language designed for safety.

## Foundations: Formal Methods Applicable to Rust

### Model Checking with Prusti and KLEE

Prusti is a verification tool that translates annotated Rust code into the Viper verification backend. It can automatically discharge many safety properties:

```rust
#[requires(ptr.is_null() == false)]
#[ensures(*ptr == old(*ptr))]
fn read(ptr: *const u8) -> u8 {
    unsafe { *ptr }
}
```

The annotations (`#[requires]`, `#[ensures]`) become verification conditions checked by an SMT solver. Prusti excels at **memory‑safety** and **functional correctness** for pure code, but it struggles with complex concurrency patterns.

KLEE, though originally a C/C++ symbolic executor, can be used on Rust binaries compiled to LLVM IR. By feeding the IR to KLEE, you can explore execution paths that involve unsafe blocks:

```bash
cargo rustc --release -- -C embed-bitcode=yes
klee --optimize --output-dir=klee-out target/release/deps/mycrate-*.bc
```

KLEE will report potential out‑of‑bounds accesses or null dereferences that escaped static analysis.

### Proof Assistants: Coq, Isabelle/HOL, and RustBelt

When model checking hits its limits—particularly for **concurrency** and **low‑level hardware interactions**—interactive proof assistants become indispensable.

- **RustBelt** provides a semantic framework for reasoning about unsafe Rust code. It formalizes the *ownership* and *lifetime* rules in a higher‑order logic, allowing you to prove that an `unsafe fn` respects its contract.
- **Coq** can encode the semantics of a Rust module and let you write proofs that certain invariants are never violated. The `rustproof` library offers a shallow embedding of Rust’s core language.
- **Isabelle/HOL** has been used to verify the `seL4` microkernel, demonstrating that the same techniques can be applied to Rust kernels or hypervisors.

A typical workflow is:

1. Write a *specification* in Coq describing the intended state machine (e.g., “DMA buffer must be locked before reconfiguration”).
2. Export the Rust implementation’s LLVM IR.
3. Prove a *simulation* theorem that the IR refines the Coq model.

### Type‑Level Specifications

Rust’s type system can express many safety properties without external tools. Libraries like `typestate` and `ghostcell` embed *state machines* into the type system, turning illegal transitions into compile‑time errors. While not a full formal verification, they form a useful first line of defense.

```rust
use typestate::Typestate;

#[derive(Typestate)]
enum DmaState {
    Idle,
    Configured,
    InProgress,
}
```

## Toolchain Integration

### Setting Up Prusti

1. Install the latest Prusti release:

   ```bash
   cargo install prusti-cli
   ```

2. Add the Prusti attributes to your `Cargo.toml`:

   ```toml
   [dependencies]
   prusti-contracts = "0.8"
   ```

3. Verify a crate:

   ```bash
   prusti-rustc src/lib.rs
   ```

Prusti will emit a detailed report showing which verification conditions succeeded or failed. For large codebases, you can **incrementally verify** by enabling `#[prusti::verify]` only on modules under active development.

### Using MIRAI for Abstract Interpretation

MIRAI is a static analyzer that works on Rust’s Mid‑level IR (MIR). It can catch **dereference‑after‑free** and **integer overflow** bugs that the borrow checker misses.

```bash
cargo install mirai
mirai --check-panic src/lib.rs
```

MIRAI integrates with CI pipelines; its JSON output can be fed to a dashboard for trend analysis.

### Combining Model Checking and Proof Assistants

A practical pipeline looks like:

1. **Run Prusti** on all safe code; fix any failing contracts.
2. **Execute KLEE** on the compiled LLVM bitcode for the unsafe modules.
3. **Export invariants** discovered by Prusti (e.g., `#[ensures]` clauses) as Coq lemmas.
4. **Discharge remaining lemmas** in Coq, leveraging the RustBelt framework.

Automation can be achieved with a `Makefile`:

```make
verify: prusti kelly coq

prusti:
    prusti-rustc src/**/*.rs

kelly:
    cargo rustc --release -- -C embed-bitcode=yes
    klee --output-dir=klee-out target/release/deps/*.bc

coq:
    coqc -Q src/ CoqProofs/
```

## Case Study: Verifying a Critical Transition in an Embedded Driver

Consider an STM32 DMA driver where the buffer must be *locked* before reconfiguration and *unlocked* after the transfer completes. A bug in the original firmware caused a hard‑fault when an interrupt fired during reconfiguration.

### Defining Safety Invariants

1. **Lock Invariant** – While `DMA.locked == true`, the buffer pointer must not be accessed by any ISR.
2. **State Machine** – `Idle → Configured → InProgress → Idle`.

These invariants are expressed in Coq:

```coq
Inductive dma_state :=
| Idle
| Configured
| InProgress.

Definition lock_inv (s: dma_state) (locked: bool) :=
  match s, locked with
  | InProgress, true => False   (* illegal: buffer accessed while locked *)
  | _, _ => True
  end.
```

### Writing Specifications in Prusti

```rust
#[requires(!self.locked)]
#[ensures(self.locked)]
pub fn lock(&mut self) {
    unsafe { self.registers.cr.modify(|_, w| w.en().set_bit()) };
    self.locked = true;
}

#[requires(self.locked)]
#[ensures(!self.locked)]
pub fn unlock(&mut self) {
    unsafe { self.registers.cr.modify(|_, w| w.en().clear_bit()) };
    self.locked = false;
}
```

Prusti verifies that `lock` can only be called when the driver is not already locked, and that `unlock` restores the unlocked state.

### Automated Proof and Manual Coq Proof

Prusti automatically discharges the functional correctness of `lock`/`unlock`. However, the *concurrency* property—no ISR may read the buffer while `locked == true`—requires a Coq proof that the ISR respects the lock invariant. The proof proceeds by:

1. Modeling the ISR as a function `isr(buf: *mut u8)`.
2. Showing that `isr` reads the buffer only under the guard `if !driver.locked { … }`.
3. Using the `lock_inv` lemma to conclude safety.

The final Coq script compiles to a small artifact that can be attached to the repository for audit.

## Best Practices and Pitfalls

- **Start Small** – Verify a single unsafe function before tackling an entire crate. This reduces proof churn.
- **Treat Specifications as Code** – Keep them in version control, run linters, and review them in PRs.
- **Avoid Specification Debt** – When a function’s contract changes, update both the Prusti annotations and any Coq lemmas simultaneously.
- **Performance Awareness** – Heavy verification can slow CI; use caching (`prusti-cache`) and run full proofs nightly.
- **Tool Compatibility** – Some crates rely on nightly features that Prusti or MIRAI do not yet support; isolate those crates behind feature flags.

## Key Takeaways

- Rust’s borrow checker is powerful but not omnipotent; formal verification fills the remaining safety gaps.
- Model checking (Prusti, KLEE) handles most functional correctness and memory‑safety properties automatically.
- Proof assistants (Coq, Isabelle/HOL) are essential for reasoning about concurrency, hardware interactions, and complex invariants.
- A layered pipeline—static analysis → model checking → interactive proof—offers the best trade‑off between effort and assurance.
- Incremental verification, clear specifications, and CI integration are the keys to scaling formal methods in real‑world Rust projects.

## Further Reading

- [RustBelt: Securing Unsafe Rust](https://plv.mpi-sws.org/rustbelt/)
- [Prusti – Formal Verification for Rust](https://www.pm.inf.ethz.ch/research/prusti/)
- [KLEE – Symbolic Execution Engine](https://klee.github.io/)
- [MIRAI – Abstract Interpretation for Rust](https://github.com/facebookexperimental/MIRAI)
- [The Rustonomicon – The Dark Arts of Unsafe Rust](https://doc.rust-lang.org/nomicon/)