---
title: "Formatting Code Across Languages: Prettier, Biome, Ruff, Black, gofmt, and rustfmt"
date: "2026-03-31T16:40:51.566"
draft: false
tags: ["code formatting","tooling","development","best practices","language-specific"]
---

## Introduction

In modern software development, *consistent* code style is no longer a luxury—it’s a necessity. A well‑formatted codebase reduces cognitive load, prevents trivial merge conflicts, and makes onboarding new team members smoother. Over the past decade a rich ecosystem of formatters has emerged, each tailored to a specific language or set of languages, and each with its own philosophy about what “beautiful” code looks like.

This article provides an in‑depth, language‑agnostic tour of six of the most popular formatters today:

| Formatter | Primary Language(s) | Year Introduced | Core Philosophy |
|-----------|---------------------|-----------------|-----------------|
| **Prettier** | JavaScript, TypeScript, HTML, CSS, JSON, Markdown, etc. | 2017 | “One style, no configuration.” |
| **Biome** | JavaScript/TypeScript, JSON, CSS, HTML, Markdown, etc. (Rust‑based) | 2023 | Fast, extensible, and opinionated with optional overrides. |
| **Ruff** | Python (linter + formatter) | 2023 | Ultra‑fast, single‑binary, zero‑config for most projects. |
| **Black** | Python | 2018 | “The uncompromising code formatter.” |
| **gofmt** | Go | 2009 (built‑in) | Enforces the canonical Go style; part of the toolchain. |
| **rustfmt** | Rust | 2015 (official) | Aligns with the Rust style guide; integrated with Cargo. |

By the end of this guide you will understand:

1. **Why you need a formatter** and how it differs from a linter.
2. **The design goals** and trade‑offs of each tool.
3. **How to integrate** them into local development, CI/CD pipelines, and editor workflows.
4. **Practical configuration** examples and real‑world usage patterns.
5. **Performance considerations** and when to pick one over another.

Let’s dive in.

---

## 1. The Role of a Code Formatter

### 1.1 Formatting vs. Linting

- **Formatting**: Transforms source code to adhere to a deterministic style (indentation, line length, spacing, quote style, etc.). The output is always the same given the same input, regardless of context.
- **Linting**: Analyzes code for potential bugs, anti‑patterns, or style violations that may not be automatically fixable (e.g., unused variables, ambiguous naming).

While many tools combine both capabilities (e.g., Ruff), separating concerns allows teams to adopt a *format‑first* workflow: run the formatter on every save, then run linters for deeper quality checks.

> **Note**  
> The “format‑first” approach reduces the number of style‑related comments in code reviews, letting reviewers focus on logic and architecture.

### 1.2 Benefits of Automatic Formatting

- **Consistency** across the entire codebase, even when multiple developers have different personal styles.
- **Reduced cognitive load**: developers no longer need to decide on line breaks or brace placement.
- **Fewer merge conflicts**: whitespace is no longer a source of diffs.
- **Speedy onboarding**: new contributors can start coding immediately without learning a style guide.
- **Enforced best practices**: many formatters embed community‑approved conventions (e.g., double quotes for strings in JSON).

---

## 2. Prettier – The “One Style” Formatter

### 2.1 Overview

Prettier is arguably the most widely adopted formatter for front‑end ecosystems. It supports a large list of file types (JS/TS, JSX, Vue, Svelte, CSS, SCSS, JSON, YAML, Markdown, etc.) and strives to eliminate *any* configuration debate by offering a single, opinionated style.

### 2.2 Installing and Running Prettier

```bash
# Install globally (optional)
npm install -g prettier

# Or add as a dev dependency
npm install --save-dev prettier
```

You can format a file directly from the CLI:

```bash
prettier --write src/index.ts
```

Or format an entire project:

```bash
prettier --write "**/*.{js,ts,tsx,css,html,md}"
```

### 2.3 Configuration (Optional)

Although Prettier is “zero‑config,” you can override a few settings via a `.prettierrc` file:

```json
{
  "printWidth": 100,
  "tabWidth": 2,
  "singleQuote": true,
  "trailingComma": "es5"
}
```

> **Pro tip**: Keep the overrides minimal; the more you deviate, the less you benefit from the “no‑debate” philosophy.

### 2.4 Editor Integration

- **VS Code**: Install the “Prettier - Code formatter” extension and set `"editor.formatOnSave": true` in `settings.json`.
- **Neovim (Lua)**: Use `null-ls` or `formatter.nvim` to call Prettier on save.
- **WebStorm**: Built‑in support; enable “Reformat on file save.”

### 2.5 Real‑World Use Cases

- **Open‑source libraries**: Many React component libraries (e.g., Chakra UI, Material‑UI) enforce Prettier in CI.
- **Monorepos**: With tools like `lerna` or `pnpm workspaces`, a single Prettier config can be shared across many packages.

---

## 3. Biome – The Rust‑Powered Successor

### 3.1 What Is Biome?

Biome (formerly known as “Rome”) is a newer, Rust‑based formatter and linter for JavaScript/TypeScript and related front‑end assets. Its goals are:

1. **Speed**: Rust’s zero‑cost abstractions make Biome up to 10× faster than Prettier on large codebases.
2. **Extensibility**: Built‑in lint rules that can be toggled on/off.
3. **Unified experience**: One binary for linting, formatting, and even type‑checking (via integration with `tsc`).

### 3.2 Installation

```bash
# Using npm (the binary is pre‑compiled)
npm install -g @biomejs/biome

# Or via Cargo (if you like Rust tooling)
cargo install biome-cli
```

### 3.3 Basic Usage

```bash
# Format a single file
biome format src/app.ts

# Format an entire project (default looks for .biome.json)
biome format .
```

### 3.4 Configuration

Biome uses a JSON configuration file `.biome.json`:

```json
{
  "formatter": {
    "lineWidth": 120,
    "indentStyle": "space",
    "indentSize": 2,
    "quoteStyle": "double"
  },
  "linter": {
    "rules": {
      "noUnusedVariables": "error",
      "noConsoleLog": "warn"
    }
  }
}
```

You can also generate a baseline config:

```bash
biome init
```

### 3.5 Integration with Editors

- **VS Code**: Install the “Biome” extension. It supports both linting and formatting on save.
- **Neovim**: Use `null-ls` or `efm-langserver` to forward formatting requests to Biome.
- **CLI in CI**: Add a step in GitHub Actions:

```yaml
- name: Install Biome
  run: npm i -g @biomejs/biome
- name: Run Biome
  run: biome check .
```

### 3.6 When to Choose Biome Over Prettier

| Scenario | Prettier | Biome |
|----------|----------|-------|
| **Existing large JS/TS project** | Mature ecosystem, many plugins | Faster formatting on CI, built‑in linting |
| **Need custom lint rules** | Requires ESLint + Prettier combos | Linter integrated, same binary |
| **Team values minimal configuration** | Strong “no‑config” stance | Still opinionated but offers granular toggles |
| **Toolchain homogeneity** | Separate CLI + ESLint | Single binary for lint + format |

---

## 4. Ruff – The Lightning‑Fast Python Linter + Formatter

### 4.1 Introducing Ruff

Ruff is a relatively new Python tool that bundles linting, type checking, and formatting into a single, ultra‑fast binary written in Rust. Its primary goals:

- **Speed**: Up to 100× faster than `flake8` + `black` combined.
- **Zero‑config default**: Works out‑of‑the‑box for most projects.
- **Compatibility**: Mirrors many popular flake8/pycodestyle rules.

### 4.2 Installation

```bash
# Using pip (binary wheels are provided)
pip install ruff

# Verify installation
ruff --version
```

### 4.3 Running Ruff

```bash
# Lint only (default)
ruff check src/

# Auto‑fix (includes formatting)
ruff check src/ --fix
```

Ruff’s `--fix` flag automatically applies format‑related fixes (e.g., trailing commas, line length) that are equivalent to Black’s output.

### 4.4 Configuration

Ruff reads a `pyproject.toml` file. Minimal example:

```toml
[tool.ruff]
line-length = 88
select = ["E", "F", "W", "C90"]
ignore = ["E501"]  # Let Ruff handle line length via formatter
```

If you want Black‑compatible formatting, enable the `format` rule set:

```toml
[tool.ruff.format]
preview = true  # Enables experimental Black-style formatting
```

### 4.5 Editor Integration

- **VS Code**: Install the “Ruff” extension. It provides diagnostics and auto‑fix on save.
- **Neovim (Lua)**: Use `null-ls` with the `ruff` source.
- **Pre‑commit**: Add to `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/astral-sh/ruff-pre-commit
  rev: v0.4.0
  hooks:
    - id: ruff
      args: [--fix]
```

### 4.6 When to Use Ruff

| Need | Recommended Tool |
|------|-------------------|
| **Maximum speed** on large monorepos | Ruff |
| **Strict adherence to Black’s style** | Black (or Ruff with `format.preview`) |
| **Fine‑grained lint rule selection** | Ruff (supports hundreds of rule IDs) |
| **Existing flake8 configuration** | Ruff can import flake8 rules automatically |

---

## 5. Black – The “Uncompromising” Python Formatter

### 5.1 Philosophy

Black’s mantra is “There is only one way to format Python code.” By removing style debates, Black makes code reviews faster and encourages a uniform codebase. It enforces:

- 88‑character line length (configurable)
- Double quotes for strings (unless single quotes avoid escaping)
- Trailing commas in multi‑line constructs

### 5.2 Installing Black

```bash
pip install black
```

### 5.3 Basic Usage

```bash
# Format a single file
black src/main.py

# Format a whole project
black .
```

### 5.4 Configuration Options

Black reads a `pyproject.toml` file. Minimal example:

```toml
[tool.black]
line-length = 100
skip-string-normalization = true   # Keep original quote style
target-version = ['py38']
```

### 5.5 Editor Integration

- **VS Code**: “Python” extension includes Black; enable `"python.formatting.provider": "black"` and `"editor.formatOnSave": true`.
- **PyCharm**: Settings → Tools → Black Formatter.
- **Neovim**: Use `null-ls` or `formatter.nvim` with the Black command.

### 5.6 Black vs. Ruff Formatting

Both tools can format Python code, but there are subtle differences:

| Feature | Black | Ruff (format preview) |
|---------|-------|-----------------------|
| **Line‑wrap algorithm** | Uses `black`'s own algorithm (often more aggressive) | Mirrors Black but may have minor differences |
| **Quote handling** | Normalizes to double quotes by default | Can preserve original quotes unless configured |
| **Speed** | Fast, but slower than Ruff (written in Python) | Faster (Rust implementation) |
| **Ecosystem** | Widely adopted, many CI templates | Newer, still gaining traction |

If you already use Black, Ruff can complement it as a linter, but you rarely need both formatters.

---

## 6. gofmt – The Built‑In Go Formatter

### 6.1 The Go Philosophy

Go’s creator, Rob Pike, deliberately baked formatting into the language’s toolchain. `gofmt` is part of the standard Go distribution, guaranteeing that **every** Go program can be formatted the same way, regardless of the developer’s editor.

### 6.2 Running gofmt

```bash
# Format a single file
gofmt -w main.go

# Recursively format a module
gofmt -w .
```

The `-w` flag writes the changes back to the file. Without it, `gofmt` prints the formatted code to stdout.

### 6.3 Integration with Go Modules

Many Go developers rely on `go vet` and `go test` pipelines, but `gofmt` can be added as a pre‑commit hook:

```bash
# .git/hooks/pre-commit
#!/bin/sh
gofmt -l -w .
git add -u
```

### 6.4 Editor Support

- **VS Code**: The “Go” extension automatically formats on save.
- **GoLand**: Built‑in “Reformat Code” action (Ctrl+Alt+L).
- **Neovim**: Use `vim-go` or `null-ls` with the `gofmt` source.

### 6.5 Real‑World Impact

Because `gofmt` is **mandatory** for Go code, style violations rarely appear in code reviews. Projects like Kubernetes, Docker, and the Go standard library all rely exclusively on `gofmt`.

---

## 7. rustfmt – The Official Rust Formatter

### 7.1 Overview

Rust’s official formatting tool, `rustfmt`, is maintained by the Rust team and conforms to the Rust Style Guidelines (`rustfmt` config). It ships with the Rust toolchain (`rustup component add rustfmt`).

### 7.2 Installing rustfmt

```bash
rustup component add rustfmt
```

### 7.3 Using rustfmt

```bash
# Format a single file
rustfmt src/main.rs

# Format the entire workspace
cargo fmt
```

`cargo fmt` will recursively format all crates in a workspace.

### 7.4 Configuration

`rustfmt` reads a `rustfmt.toml` file placed at the project root:

```toml
max_width = 100
hard_tabs = false
use_small_heuristics = "Max"
reorder_imports = true
```

Only a subset of options is stable; the rest are experimental and require `unstable_features = true`.

### 7.5 Editor Integration

- **VS Code**: “rust-analyzer” extension automatically formats on save using `rustfmt`.
- **IntelliJ Rust**: Built‑in support; enable “Reformat on Save”.
- **Neovim**: Use `null-ls` with the `rustfmt` source or `rust-tools.nvim`.

### 7.6 Community Adoption

Because `rustfmt` is part of the official toolchain, most crates on crates.io use it. Projects like `serde`, `tokio`, and `actix` enforce `cargo fmt --check` in CI pipelines to ensure formatting compliance.

---

## 8. Comparative Matrix

| Feature | Prettier | Biome | Ruff | Black | gofmt | rustfmt |
|---------|----------|-------|------|-------|-------|---------|
| **Language(s)** | JS/TS/HTML/CSS/JSON/MD | JS/TS/HTML/CSS/JSON/MD | Python | Python | Go | Rust |
| **Implementation Language** | JavaScript (Node) | Rust | Rust | Python | Go (built‑in) | Rust |
| **Speed (per 10k LOC)** | ~1.2 s | ~0.3 s | ~0.1 s | ~0.5 s | ~0.05 s | ~0.2 s |
| **Opinionated** | Yes (very) | Yes (with overrides) | Mostly (configurable) | Yes (very) | No (canonical) | Yes (canonical) |
| **Config File** | `.prettierrc` (JSON/YAML) | `.biome.json` | `pyproject.toml` | `pyproject.toml` | None (flags only) | `rustfmt.toml` |
| **Auto‑fix** | Yes (`--write`) | Yes (`format`) | Yes (`--fix`) | Yes (`black`) | Yes (`-w`) | Yes (`cargo fmt`) |
| **Editor Plugins** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **CLI Integration** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **License** | MIT | MIT | MIT | MIT | BSD‑3 | MIT/Apache‑2.0 |
| **Community Size** | > 2 M downloads/mo | Growing fast | Emerging | Mature | Built‑in | Mature |

---

## 9. Practical Workflow Recommendations

### 9.1 “Format‑On‑Save + CI Gate”

1. **Local Development**: Enable format‑on‑save in your IDE (VS Code, Neovim, etc.).
2. **Pre‑commit Hook**: Use `pre-commit` to run the formatter with `--check` before each commit.
3. **CI Step**: Add a “format check” stage that fails the build if code is not properly formatted.

#### Example: GitHub Actions for a Python Project (Ruff + Black)

```yaml
name: CI
on: [push, pull_request]

jobs:
  format:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - name: Install Ruff
        run: pip install ruff
      - name: Check formatting
        run: ruff check . --fix --diff
```

### 9.2 Monorepo Strategy

When a monorepo contains multiple languages (e.g., a full‑stack app with React front‑end, Python back‑end, Go micro‑services, and Rust utilities), you can orchestrate formatters with a single script:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "Formatting JavaScript/TypeScript..."
biome format .

echo "Formatting Python..."
ruff check . --fix

echo "Formatting Go..."
gofmt -w .

echo "Formatting Rust..."
cargo fmt
```

Add this script to `package.json` or a Makefile target (`make fmt`) and call it from CI.

### 9.3 Handling Exceptions

Sometimes a project needs a *local* exception (e.g., a generated file). Most formatters support ignore patterns:

- **Prettier**: `.prettierignore`
- **Biome**: `.biomeignore`
- **Ruff**: `exclude` in `pyproject.toml`
- **Black**: `exclude` in `pyproject.toml`
- **gofmt**: No built‑in ignore; use `git` exclude patterns.
- **rustfmt**: `skip_children` or `skip` attributes in code.

Example `.prettierignore`:

```
# Ignore generated files
dist/
build/
```

---

## 10. Common Pitfalls and How to Avoid Them

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Conflicting formatters** (e.g., ESLint + Prettier both trying to format) | Duplicate changes, endless diffs | Use `eslint-config-prettier` to disable conflicting rules. |
| **CI “format check” fails on line endings** | Windows vs. Unix line endings cause diff | Enforce `endOfLine: "lf"` in Prettier; add `.gitattributes` with `* text=auto`. |
| **Formatter overwrites intentional formatting** (e.g., tables in Markdown) | Table columns become misaligned | Add a `prettier-ignore` comment (`<!-- prettier-ignore -->`) before the block. |
| **Performance bottleneck on large repos** | CI step takes >5 min | Switch to a Rust‑based formatter (Biome, Ruff) or run format checks only on changed files (`git diff --name-only`). |
| **Missing formatter in CI** | Build passes locally but fails on PR | Ensure the formatter binary is installed (e.g., `npm ci`, `pip install -r requirements.txt`). |

---

## 11. Future Trends in Code Formatting

1. **AI‑Assisted Formatting**: Tools like GitHub Copilot are beginning to suggest formatting changes alongside code suggestions. Expect tighter integration between LLMs and formatters, possibly enabling *semantic* formatting (e.g., aligning related API calls).  
2. **Unified Multi‑Language Formatters**: Projects like Biome aim to replace a suite of language‑specific tools with a single binary, reducing maintenance overhead.  
3. **Incremental Formatting**: Instead of reformatting the whole repository, next‑gen formatters may only touch the edited region, dramatically speeding up CI for massive monorepos.  
4. **Standardized Config Schemas**: A movement toward a common `formatter.toml` could simplify cross‑language projects, letting a single config drive Prettier, Biome, and Black.

---

## Conclusion

Automatic code formatting is no longer a “nice‑to‑have” but a cornerstone of modern development practices. Whether you’re building a single‑page React app, a data‑science Python library, a high‑performance Go service, or a systems‑level Rust crate, a dedicated formatter ensures that your codebase remains clean, readable, and merge‑conflict‑free.

- **Prettier** shines in the JavaScript ecosystem with its zero‑configuration stance.  
- **Biome** offers a Rust‑powered, faster alternative with built‑in linting.  
- **Ruff** brings lightning‑fast linting and formatting to Python, rivaling Black in speed while remaining configurable.  
- **Black** remains the go‑to opinionated formatter for teams that prefer a single, community‑approved style.  
- **gofmt** and **rustfmt** demonstrate the power of embedding formatting directly into a language’s toolchain, guaranteeing canonical style across the ecosystem.

By adopting a **format‑on‑save** workflow, enforcing a **CI format check**, and leveraging **pre‑commit hooks**, you can eliminate style debates, reduce review friction, and keep your codebase healthy for the long term.

Happy formatting!

## Resources

- [Prettier – Official Site](https://prettier.io)
- [Biome – Documentation & CLI](https://biomejs.dev)
- [Ruff – Fast Python Linter & Formatter](https://docs.astral.sh/ruff)
- [Black – The Uncompromising Code Formatter](https://black.readthedocs.io)
- [gofmt – Go Formatting Tool (golang.org)](https://golang.org/cmd/gofmt/)
- [rustfmt – Rust Code Formatter](https://github.com/rust-lang/rustfmt)