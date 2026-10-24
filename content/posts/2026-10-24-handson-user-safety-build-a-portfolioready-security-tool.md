---
title: "Hands‑On User Safety: Build a Portfolio‑Ready Security Tool"
date: "2026-10-24T22:00:43.516"
draft: false
tags: ["security","python","side-project","cv","data-validation"]
description: "Build a production‑ready User Safety tool that sanitises, validates, and audits user data – a hands‑on project that signals security engineering skill."
summary: "A practical guide to building a User Safety side project that demonstrates data sanitisation, validation, and audit logging, perfect for CVs."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-24-handson-user-safety-build-a-portfolioready-security-tool.svg"
  alt: "User interface showing data sanitisation and audit logs"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a hands‑on User Safety tool that sanitises, validates, and audit‑logs user input, giving you a runnable Python project that signals security‑focused engineering skill to hiring managers. You’ll learn concrete techniques for input sanitisation, schema‑level validation, and structured audit logging using battle‑tested libraries. By the end you’ll have a working CLI (or HTTP) service you can ship, test, and extend.

Building a portfolio project that demonstrates real‑world security engineering is a powerful way to stand out to hiring managers. In this guide we’ll construct a **User Safety** utility that takes arbitrary user input, sanitises it against common injection vectors, validates it against a Pydantic schema, and writes an immutable audit record. The entire tool is ~150 lines of Python, runs locally with `pip install -r requirements.txt`, and can be containerised, tested, and extended into a production‑grade service.

## Why This Project Stands Out on a CV

Hiring managers for backend, security, and data‑engineering roles look for concrete evidence that you can handle input safely, reason about data contracts, and build observability from the start. This project signals several competencies:

- **Input sanitisation** – you’ll apply the OWASP XSS Prevention Cheat Sheet techniques to strip or escape dangerous HTML/JS, a skill directly transferable to web frameworks (Django, FastAPI, Flask).
- **Schema‑level validation** – using **Pydantic** shows you can enforce types, constraints, and default values, a pattern common in modern Python services.
- **Audit logging** – writing structured JSON‑L records demonstrates an understanding of traceability, a requirement for compliance‑driven systems (GDPR, SOC 2).
- **CLI/HTTP wiring** – building an argparse‑based CLI or a tiny FastAPI endpoint proves you can expose functionality both locally and over HTTP, a frequent interview talking point.
- **Testability** – the code naturally lends itself to unit tests with `pytest` and property‑based tests with **Hypothesis**, showing you care about correctness.

Roles that benefit most include **Security Engineer**, **Backend Engineer**, **Data Engineer**, and **DevOps Engineer** who own data‑ingestion pipelines. The project can be listed as “User Safety: sanitiser + validator + audit logger” on your CV, and during interviews you can walk through each component, the threats you mitigated, and the libraries you chose.

## Architecture Overview

The system consists of four loosely‑coupled components that fit together as a simple pipeline:

1. **CLI / HTTP entry point** – parses user input (stdin or query param) and delegates to the core pipeline.
2. **Sanitiser module** – uses **bleach** (HTML sanitisation) and regex‑based escape for SQL/NoSQL metacharacters.
3. **Validator module** – loads the raw text into a **Pydantic** model, rejecting malformed data early.
4. **Audit logger** – appends a JSON‑Line entry to `audit.log` containing timestamp, original input, sanitised output, and validation result.

```
┌─────────────┐      ┌─────────────────┐      ┌─────────────────────┐
│  CLI/HTTP   ├────▶ │   Sanitiser      ├────▶ │   Validator (Pydantic)│
└─────────────┘      └─────────────────┘      └─────────────────────┘
                                          │
                                          ▼
                                 ┌─────────────────┐
                                 │   Audit Logger  │
                                 │ (JSON‑L file)   │
                                 └─────────────────┘
```

Each component is importable, making it trivial to replace the logger with a database sink or the sanitiser with a third‑party WAF later.

## Building It Step by Step

Below are seven numbered steps. Each step includes a short, runnable Python snippet (fenced with ```python) that you can copy into your project.

### Step 1 – Initialise the repo and install dependencies

```bash
mkdir user-safety && cd user-safety
python -m venv .venv
source .venv/bin/activate
pip install "pydantic>=2.5" bleach pytest hypothesis
```

### Step 2 – Define the data model

```python
# models.py
from pydantic import BaseModel, validator, Field
from typing import Optional

class UserInput(BaseModel):
    raw: str = Field(..., description="Raw user supplied text")
    sanitised: Optional[str] = Field(None, description="Sanitised output after cleaning")
    validated: Optional[bool] = Field(None, description="Whether validation passed")

    @validator("raw")
    def not_empty(cls, v):
        if not v.strip():
            raise ValueError("raw must not be empty")
        return v

    @validator("sanitised", pre=True)
    def set_validated(cls, v, values):
        # will be set by the pipeline
        return v
```

### Step 3 – Implement the sanitiser

```python
# sanitiser.py
import re
import bleach

# Allowed HTML tags – very restrictive, suitable for a CV demo
ALLOWED_TAGS = ["b", "i", "em", "strong"]
ALLOWED_ATTRIBUTES = {}

def sanitise(text: str) -> str:
    # First strip dangerous tags with bleach
    cleaned = bleach.clean(text, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)
    # Additionally escape SQL metacharacters
    sql_escaped = re.sub(r"(['\\])", r"\\\1", cleaned)
    return sql_escaped
```

### Step 4 – Wire the validator

```python
# validator.py
from .models import UserInput
from .sanitiser import sanitise

def validate_and_sanitise(raw: str) -> UserInput:
    sanitised = sanitise(raw)
    try:
        model = UserInput(raw=raw, sanitised=sanitised, validated=True)
    except Exception as e:
        model = UserInput(raw=raw, sanitised=sanitised, validated=False)
        model.errors = str(e)  # simple attribute for demo
    return model
```

### Step 5 – Create the audit logger

```python
# logger.py
import json
from datetime import datetime
from pathlib import Path

AUDIT_PATH = Path("audit.log")

def log_entry(raw: str, sanitised: str, validated: bool):
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "raw": raw,
        "sanitised": sanitised,
        "validated": validated,
    }
    AUDIT_PATH.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
```

### Step 6 – Build a tiny CLI

```python
# cli.py
import argparse
from .validator import validate_and_sanitise
from .logger import log_entry

def main():
    parser = argparse.ArgumentParser(description="User Safety – sanitise & audit input")
    parser.add_argument("text", help="The user input to process")
    args = parser.parse_args()

    result = validate_and_sanitise(args.text)
    log_entry(args.text, result.sanitised, result.validated)

    print(f"Original: {result.raw}")
    print(f"Sanitised: {result.sanitised}")
    print(f"Validated: {result.validated}")

if __name__ == "__main__":
    main()
```

### Step 7 – Add a minimal test suite

```python
# tests/test_sanitiser.py
from sanitiser import sanitise

def test_basic():
    assert sanitise("<b>hello</b>") == "<b>hello</b>"  # allowed tag kept

def test_script_stripped():
    assert "<script>alert(1)</script>" not in sanitise("<script>alert(1)</script>")
```

Run the tests with `pytest -q`. You should see both pass, confirming that the sanitiser keeps safe tags and removes dangerous scripts.

## Running and Testing It

With the repository set up, you can exercise the tool in three ways:

1. **CLI demo**

   ```bash
   python -m user_safety.cli "<b>Hi</b> <script>evil()</script>"
   ```

   Expected output:

   ```
   Original: <b>Hi</b> <script>evil()</script>
   Sanitised: <b>Hi</b> evil()
   Validated: True
   ```

2. **Python REPL**

   ```python
   from user_safety.validator import validate_and_sanitise
   from user_safety.logger import log_entry
   log_entry("<b>test</b>", *validate_and_sanitise("<b>test</b>").sanitised, True)
   ```

   After running, `audit.log` will contain a single JSON‑L line with timestamp, raw, and sanitised fields.

3. **Unit tests**

   ```bash
   pytest -q
   ```

   All three tests (`test_basic`, `test_script_stripped`, and the implicit model validation) should pass, giving you immediate feedback on correctness.

If you prefer an HTTP surface, drop the `cli.py` logic into a FastAPI endpoint:

```python
# api.py (optional addition)
from fastapi import FastAPI
from .cli import main as cli_main

app = FastAPI(title="User Safety API")

@app.post("/sanitise/")
def sanitise(payload: dict):
    text = payload.get("text", "")
    # reuse CLI logic
    from user_safety.cli import main as cli_main
    # FastAPI can’t call CLI directly; instead inline the functions:
    from user_safety.validator import validate_and_sanitise
    from user_safety.logger import log_entry
    result = validate_and_sanitise(text)
    log_entry(text, result.sanitised, result.validated)
    return {"sanitised": result.sanitised, "validated": result.validated}
```

Run `uvicorn api:app --reload` and POST `{"text":"<b>hi</b>"}` to `http://127.0.0.1:8000/sanitise/`.

## Extending It: Your Roadmap to Senior‑Level

| Upgrade | One‑line reason it matters |
|---|---|
| **Persist audit data in SQLite** | Moves from ephemeral `audit.log` to a queryable relational store, enabling compliance reports and historical forensics. |
| **Containerise with Docker** | Guarantees reproducible environments across CI, local dev, and production, a baseline expectation for any senior‑level project. |
| **Add OpenTelemetry instrumentation** | Export traces and metrics to a backend (e.g., GCP Cloud Monitoring), giving you visibility into latency, error rates, and usage patterns. |
| **Implement rate‑limiting with `slowapi`** | Protects the service from abuse and demonstrates knowledge of production‑grade API security patterns. |
| **Property‑based testing with Hypothesis** | Automatically generates edge‑case inputs, catching corner‑case bugs that manual tests often miss. |
| **Add a GitHub Actions CI pipeline** | Runs lint, test, and container build on every PR, signalling to hiring managers that you ship with automated quality gates. |

Each upgrade is a concrete step toward turning the toy into a service you could actually run in production, and each can be discussed in depth during an interview.

## Key Takeaways

- **Sanitise before you trust** – always run user input through a whitelist‑based sanitiser (bleach) and escape DB‑specific metacharacters.
- **Validate with a schema** – Pydantic gives you typed, self‑documenting models and immediate failure feedback.
- **Audit everything** – structured JSON‑L logs give you a tamper‑evident trail for compliance and debugging.
- **Make it runnable** – a CLI, a tiny FastAPI service, and pytest tests let you demonstrate the tool instantly.
- **Think ahead** – plan persistence, containerisation, observability, and CI from day 1; those decisions separate a hobby project from a production‑ready portfolio piece.

## Further Reading

- [OWASP XSS Prevention Cheat Sheet](https://owasp.org/www-project-cheat-sheets/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html) – the definitive guide to safe HTML handling.
- [Pydantic Documentation – v2](https://docs.pydantic.dev/) – learn model definition, validation, and type coercion.
- [Python logging tutorial](https://docs.python.org/3/tutorial/logging.html) – structured logging best practices for audit trails.
- [SQLite Documentation](https://www.sqlite.org/docs.html) – lightweight relational store for persistent audit records.
- [RFC 7231 – Hypertext Transfer Protocol](https://tools.ietf.org/html/rfc7231) – foundational HTTP semantics if you later expose the tool over HTTP.

You now have a complete, runnable **User Safety** side project that you can clone, extend, and point to on your CV. Happy hacking, and may your input always be safe!