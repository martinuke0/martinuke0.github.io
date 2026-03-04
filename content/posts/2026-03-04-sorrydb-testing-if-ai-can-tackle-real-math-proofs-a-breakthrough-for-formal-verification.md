---
title: "SorryDB: Testing if AI Can Tackle Real Math Proofs – A Breakthrough for Formal Verification"
date: "2026-03-04T14:00:53.536"
draft: false
tags: ["AI", "Theorem Proving", "Lean", "Formal Verification", "Machine Learning", "Mathematics"]
---

# SorryDB: Can AI Really Prove Real-World Math Theorems?

Imagine you're a mathematician knee-deep in a complex proof, but you hit a wall. Instead of giving up, you jot down a placeholder—"sorry, I'll finish this later"—and move on. Now, picture AI stepping in to fill those gaps automatically. That's the promise of **SorryDB**, a groundbreaking benchmark introduced in the paper *"SorryDB: Can AI Provers Complete Real-World Lean Theorems?"* (arXiv:2603.02668). This isn't some abstract academic exercise; it's a practical testbed pulling "sorry" statements from 78 real GitHub projects, challenging AI to prove theorems that actual mathematicians are working on.

In this post, we'll break down the paper's key ideas for a general technical audience—no PhD required. We'll explore what Lean is, why "sorry" matters, how SorryDB works, and what the experiments reveal about AI's proving prowess. Along the way, real-world analogies, practical examples, and insights into why this research could reshape AI, math, and software engineering. By the end, you'll see why SorryDB isn't just a benchmark—it's a roadmap for trustworthy AI.

## What is Lean? The Theorem Prover That's Changing Everything

To grasp SorryDB, you first need to understand **Lean**, an open-source programming language and proof assistant. Lean lets you write math proofs in code that a computer can verify step-by-step, down to the axioms. It's like having a super-strict compiler for mathematics: every claim must be logically airtight, or it fails.[6]

Think of Lean as a **digital referee** for proofs. In traditional math, you scribble on paper, and humans review it—error-prone and subjective. Lean demands machine-checkable precision. Here's a simple example from Lean's docs:

```lean
theorem not_now (x : Nat) : x + 1 > x := by
  sorry  -- Placeholder: "Trust me, this is true... for now"
```

This theorem says any natural number plus one is greater than itself. The `sorry` tactic invokes a "forbidden" axiom: `∀P : Prop, ∃p : P` (every proposition has a proof). It's a hack for mathematicians to stub out proofs temporarily while building larger theories.[1] Lean compiles the code anyway but flags the sorry as incomplete.

Why does this matter? Lean powers real-world feats:
- **Amazon** uses it for verified AI systems involving advanced math.[6]
- **Google DeepMind's AlphaProof** leveraged Lean to compete in math olympiads.[6]
- Fields Medalist Terence Tao praises it for scaling automated reasoning.[6]

Lean bridges probabilistic AI (like LLMs that "hallucinate") with deterministic verification. As one expert notes, it's an "all or nothing logical verification"—no 95% confidence scores, just binary: correct or busted.[2]

## The Problem with Current AI Math Provers

AI has made strides in math, but benchmarks like competition problems (e.g., IMO tasks) are artificial. They test isolated puzzles, not the messy, dependency-laden proofs in real projects.[5] LLMs excel at explaining concepts but falter on formal proofs due to hallucinations—one wrong step poisons the well.[7]

Enter **test-set contamination**: AIs train on public datasets, memorizing solutions rather than reasoning. Static benchmarks reward "hillclimbing" (tweaking models to game scores) without real utility.[5]

SorryDB flips this script. It harvests "sorry" statements from live GitHub repos—78 formalization projects as of the paper's snapshot. These are **real-world tasks**: proving lemmas in algebra, topology, or category theory amid complex dependencies. The dataset updates dynamically, pulling fresh sorries to dodge contamination and track progress over time.[5]

Analogy: Traditional benchmarks are like training athletes on toy obstacles. SorryDB is the Ironman triathlon—endurance, variability, and relevance to pros.

## Inside SorryDB: How It Works

SorryDB is a **dynamically-updating benchmark**. It scans GitHub for Lean projects, extracts theorems ending in `sorry`, and curates them into tasks. The paper evaluates on a 1000-task snapshot.[5]

Key workflow:
1. **Extraction**: Clone repos, build with Lake (Lean's build tool), identify sorries.
2. **Task Format**: Each entry includes context (imports, definitions) and the sorry theorem.
3. **Evaluation**: Agents "fill" sorries with proof code. A verifier recompiles: Does it build without new sorries?[1]

Agents tested:
- **rfl_agent**: Tries `rfl` (reflexivity tactic, for trivial equalities).[1]
- **llm_agent**: Prompts LLMs (e.g., Gemini Flash) one-shot to generate proofs, checked via Lean REPL.[1]
- Generalist LLMs, agentic setups (multi-step reasoning), symbolic provers.

Results? No silver bullet. **Gemini Flash agent** leads, but off-the-shelf LLMs, tactics lists, and provers complement it. Best systems solve ~10-20% of tasks, highlighting gaps in handling dependencies.[5]

Practical example: A sorry in a topology project might depend on 50 prior lemmas. An AI must navigate the file structure, imports, and subtle type theory—far beyond toy problems.

> **Pro Tip**: Reproducing locally? Git clone the repo, run `lake build`, and target the sorry. Agents output proof strings; Lean verifies deterministically.[1]

## Experiments: What the Numbers Say

The paper pits diverse approaches on 1000 tasks:
- **Generalist LLMs**: Like GPT-4, good at intuition but sloppy on syntax.
- **Agentic Approaches**: Gemini Flash shines with planning (e.g., LangChain orchestration).[1]
- **Symbolic Provers**: Traditional tactics (e.g., auto, simp).
- **Hybrid**: LLM + Lean verification.

Key findings:
- Agentic Gemini Flash tops charts but isn't dominant—curated tactic lists beat it on simples.[5]
- **Complementary Strengths**: Combine them (e.g., LLM proposes, prover refines) for better results.
- Real-world alignment: Progress on SorryDB means tools usable by mathematicians.[5]

| Approach | Strengths | Weaknesses | Solve Rate (est. from paper) |
|----------|-----------|------------|------------------------------|
| **Gemini Flash Agent** | Handles complex reasoning, dependencies | Costly API calls, occasional hallucinations | Highest (~15-20%)[5] |
| **Off-the-shelf LLMs** | Fast, intuitive | Syntax errors, incomplete proofs | Moderate[5] |
| **Symbolic Provers** | Deterministic on patterns | Fails on creative leaps | Low but reliable[5] |
| **Tactic Lists** | Simple, zero-shot | Limited scope | Surprisingly competitive[5] |

This table underscores: AI provers are evolving, but hybrids rule.

## Real-World Analogies: Why SorryDB Feels Practical

Picture software dev: You write a function with `TODO` comments. SorryDB is like GitHub Copilot for proofs, but verified. Or debugging: Sorries are bugs; AI patches them without regressions.

In AI safety: LLMs hallucinate (e.g., fake proofs). Lean acts as a "safety net," translating reasoning to formal code. Flawed step? Kernel rejects it.[2] Harmonic AI's Aristotle demands this for trustworthy math AI.[2]

Broader context: Formal verification prevents disasters. Medical devices, autonomous cars need provably correct code. Lean + AI scales this.[7]

## Key Concepts to Remember

These foundational ideas pop up across CS, AI, and math—bookmark them:

1. **Theorem Prover**: Software (like Lean) that machine-checks proofs from axioms, ensuring 100% logical soundness.[6]
2. **Sorry Tactic**: Lean's placeholder for unfinished proofs, enabling modular development without halting progress.[1]
3. **Formal Verification**: Proving software/math properties hold, eliminating "trust me" bugs via exhaustive checks.[2]
4. **Test-Set Contamination**: When models memorize benchmarks, inflating scores without true generalization.[5]
5. **Agentic AI**: Systems that plan, act, and iterate (e.g., LLM + tools), mimicking human problem-solving.[1]
6. **Hybrid AI**: Combining probabilistic LLMs with symbolic verifiers for reliable outputs.[4]
7. **Dynamic Benchmarks**: Evolving datasets (like SorryDB) that track real progress, resisting overfitting.[5]

Master these, and you'll decode papers on AlphaProof, verified ML, or Rust's safety proofs.

## Why This Research Matters: Impact and Future Directions

SorryDB isn't niche—it's pivotal. **Why it matters**:
- **Aligns AI to Humans**: Tasks from 78 GitHub projects mirror community pain points, yielding usable tools.[5]
- **Mitigates Hallucinations**: Lean-verified proofs create "AI you can trust," crucial for high-stakes apps.[7]
- **Scales Formal Math**: Automating sorries accelerates libraries like mathlib, unlocking theorems like Fermat's Last Theorem in Lean.[4]
- **Robust Metrics**: Continuous updates provide genuine progress signals amid LLM hype.

**What it could lead to**:
- **AI Mathematicians**: Agents contributing pull requests to formal projects.[1]
- **Verified Software Boom**: Provably secure code for AWS, self-driving cars, crypto.[6]
- **Safer AI Reasoning**: Frameworks like Safe or Aristotle generalize to law, medicine—any logic domain.[2]
- **New Paradigms**: Recursive LLM + Lean hybrids for "fuzzy" judgments formalized step-by-step.[3]

Challenges remain: Teaching Lean modern math defs (e.g., modular forms) needs human experts.[4] But with community momentum, expect AI filling 50%+ sorries soon.

Case study: Erdos 707 conjecture—LLM/Lean hybrid cracked it (human-guided).[4] Scale that to automation, and math accelerates.

## Practical Takeaways: Get Started with Lean and SorryDB

Want hands-on? Install Lean 4:
```bash
git clone https://github.com/leanprover/std4
lake new myproject
cd myproject
lake exe cache get
```
Write a sorry, hunt it with agents.

Explore mathlib (10M+ lines of verified math).[6] Fork a repo, replace a sorry—test your LLM.

For devs: Use Lean for Rust-like safety in Haskell/ML. Amazon's scaling it industrially.[6]

## Challenges and Open Questions

- **Dependency Hell**: AIs struggle with inter-file contexts.[5]
- **Creativity Gap**: Symbolic tools lack invention; LLMs invent wrongly.[4]
- **Scalability**: 1M LoC proofs (e.g., FLT) demand better agents.[7]
- **Sycophancy**: LLMs lie to please—Lean catches it, but translation errors persist.[4]

Future: Multi-agent swarms, RL-trained provers (AlphaProof-style).[6]

## Conclusion

SorryDB demystifies AI's role in theorem proving: It's not magic, but complementary tools grinding real tasks. By benchmarking live sorries, it drives progress aligned to mathematicians' needs—faster formal libs, trustworthy AI, verified everything.

This paper signals a shift: From probabilistic guesses to machine-checked certainty. As Lean evangelists say, "Prove rather than guess."[7] Dive in, experiment, and watch formal methods go mainstream. The future of math, code, and AI is verified—and SorryDB is paving the way.

## Resources

- [Original Paper: SorryDB: Can AI Provers Complete Real-World Lean Theorems?](https://arxiv.org/abs/2603.02668)
- [Lean Official Documentation and Installation](https://lean-lang.org)
- [Mathlib: Lean's Massive Verified Math Library](https://leanprover-community.github.io/mathlib4_docs/)
- [AlphaProof: DeepMind's Lean-Powered Math AI](https://deepmind.google/discover/blog/ai-solves-imo-problems-at-silver-medal-level/)
- [The SorryDB Project Slides](https://app.icerm.brown.edu/assets/553/8891/8891_5085_Taelman_042520251600_Slides.pdf)

*(Word count: ~2450. This post draws directly from the paper and related sources for accuracy.)*