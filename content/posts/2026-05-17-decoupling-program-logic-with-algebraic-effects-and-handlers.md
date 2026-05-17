---
title: "Decoupling Program Logic with Algebraic Effects and Handlers"
date: "2026-05-17T22:01:00.345"
draft: false
tags: ["algebraic-effects","programming-paradigms","software-design","functional-programming","handlers"]
description: "Explore how algebraic effects and handlers let developers separate concerns, simplify async code, and build extensible programs without tangled control flow."
summary: "Algebraic effects and handlers provide a principled way to decouple program logic from effectful operations, improving modularity and testability."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-17-decoupling-program-logic-with-algebraic-effects-and-handlers.svg"
  alt: "Illustration of abstract effect bubbles flowing into a handler container."
  caption: ""
  relative: false
---

> **TL;DR** — Algebraic effects let you declare *what* a program needs (e.g., I/O, state, concurrency) without tying it to *how* it is performed. Handlers then supply concrete implementations, making the core logic reusable, testable, and easy to extend.

Program logic often becomes entangled with low‑level concerns such as networking, logging, or error handling. Traditional approaches—callbacks, promises, or monad transformers—can scatter these concerns throughout the codebase, making reasoning and refactoring difficult. Algebraic effects and their handlers offer a clean separation: the program *asks* for an effect, and a *handler* decides how to answer. This article walks through the theory, practical examples, and trade‑offs of using algebraic effects to decouple logic from effects.

## What Are Algebraic Effects?

Algebraic effects are a formalism for describing *effectful operations* as abstract commands. An effect consists of a set of *operations* (the algebra) and the *type* of their results. Unlike exceptions, which have a single `raise` operation, an effect can expose many distinct operations, each with its own signature.

### Formal Definition

An effect `E` is defined by a collection of operation signatures:

```text
E = { op₁ : A₁ → B₁, op₂ : A₂ → B₂, … }
```

When a program invokes `op₁(v)`, it does **not** execute any concrete code; instead, it *suspends* and yields control to a handler that knows how to interpret `op₁`.

### Historical Note

The idea was introduced by Plotkin and Pretnar in their seminal paper “Algebraic Effects and Handlers” (2009) — see the original ACM version for a rigorous treatment [Plotkin & Pretnar, 2009](https://dl.acm.org/doi/10.1145/1596550.1596560).

### Comparison with Other Abstractions

| Abstraction | How it models effects | Typical usage | Main limitation |
|-------------|----------------------|---------------|-----------------|
| Exceptions  | Single `raise` operation | Error propagation | No fine‑grained control |
| Monads      | Sequential composition via `bind` | Pure functional pipelines | Stacking monad transformers becomes unwieldy |
| Call‑backs  | Functions passed as arguments | Asynchronous APIs | Callback hell, loss of type safety |
| **Algebraic Effects** | Multiple named operations, first‑class suspension | Decoupling logic from effect handling | Requires language/runtime support |

## Handlers: The Bridge Between Effects and Logic

A *handler* provides concrete semantics for each operation of an effect. When an effectful operation is invoked, the runtime captures the current continuation (the rest of the computation) and hands it to the handler. The handler can then:

1. **Resume** the continuation with a value (normal return).
2. **Modify** the continuation (e.g., retry, backtrack).
3. **Terminate** the computation early (e.g., abort).

### Handler Syntax in Practice

Below is a minimal example in **Python** using the experimental `effect` library (which mimics algebraic effects). The library is not part of the standard distribution but illustrates the core ideas.

```python
# Install with: pip install effect
from effect import Effect, sync_performer, perform, ComposedDispatcher

# 1️⃣ Define an effect with a single operation: `ReadLine`
class ReadLine(Effect):
    def __init__(self, prompt: str):
        self.prompt = prompt

# 2️⃣ Implement a performer (handler) for the effect
@sync_performer
def read_line_performer(dispatcher, intent):
    return input(intent.prompt)

# 3️⃣ Compose a dispatcher that knows how to handle ReadLine
dispatcher = ComposedDispatcher({
    ReadLine: read_line_performer
})

# 4️⃣ Write pure logic that *asks* for a line without caring how it is obtained
def greet_user():
    name = perform(ReadLine("What is your name? "))
    return f"Hello, {name}!"

# 5️⃣ Run the program with the dispatcher
if __name__ == "__main__":
    print(greet_user())
```

In this snippet:

* `ReadLine` declares the *what* (an input request).
* `read_line_performer` supplies the *how* (call `input`).
* `greet_user` contains only business logic; it never mentions `input`.

### Multiple Handlers and Scoping

Handlers can be nested, allowing local overrides. Consider a testing scenario where we replace the real I/O with a mock:

```python
from effect import Constant

def mock_read_line(prompt):
    # Return a deterministic value for tests
    return Constant("Alice")

mock_dispatcher = ComposedDispatcher({
    ReadLine: mock_read_line
})

# Running the same logic under a mock dispatcher yields a predictable result
print(greet_user())  # → "Hello, Alice!"
```

The same `greet_user` function works both in production and in tests without modification.

## Decoupling Logic: A Step‑by‑Step Example

Let’s build a small but realistic application: a **todo list manager** that supports persistence, logging, and concurrency. We’ll start with naïve code, then refactor using algebraic effects.

### 1️⃣ Naïve Implementation (Mixed Concerns)

```python
import json
import threading
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)

class TodoStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self._load()

    def _load(self):
        with open(self.path, "r") as f:
            self.todos = json.load(f)

    def add(self, item):
        with self.lock:
            self.todos.append({"task": item, "created": datetime.now().isoformat()})
            self._save()
            logging.info("Added task: %s", item)

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self.todos, f, indent=2)
```

*Problems*:  
* I/O (`open`, `json`) is interleaved with business logic (`add`).  
* Concurrency (`threading.Lock`) is forced into the same class.  
* Logging is a side‑effect spread throughout the method.

### 2️⃣ Identify the Effects

We extract three orthogonal concerns:

| Concern | Effect name | Operations |
|---------|-------------|------------|
| Persistence | `Persist` | `load() → List[Todo]`, `save(todos) → None` |
| Logging | `Log` | `info(msg) → None`, `error(msg) → None` |
| Concurrency | `Sync` | `with_lock(fn) → result` |

### 3️⃣ Declare the Effects (Python pseudo‑syntax)

```python
class Persist(Effect):
    pass

class Load(Persist):
    def __init__(self, path: str):
        self.path = path

class Save(Persist):
    def __init__(self, path: str, data):
        self.path = path
        self.data = data

class Log(Effect):
    pass

class Info(Log):
    def __init__(self, msg: str):
        self.msg = msg

class Error(Log):
    def __init__(self, msg: str):
        self.msg = msg

class Sync(Effect):
    pass

class WithLock(Sync):
    def __init__(self, fn):
        self.fn = fn
```

### 4️⃣ Pure Business Logic Using Effects

```python
def add_todo(item, path):
    # Load current list
    todos = perform(Load(path))
    # Append new entry
    todos.append({"task": item, "created": datetime.now().isoformat()})
    # Persist
    perform(Save(path, todos))
    # Log
    perform(Info(f"Added task: {item}"))
    return todos
```

Notice that `add_todo` no longer knows *how* loading, saving, or logging happen. It merely describes **what** it needs.

### 5️⃣ Implement Handlers

```python
import json, threading, logging
from effect import ComposedDispatcher, sync_performer, perform

# Persistence handler
@sync_performer
def load_performer(_, intent: Load):
    with open(intent.path, "r") as f:
        return json.load(f)

@sync_performer
def save_performer(_, intent: Save):
    with open(intent.path, "w") as f:
        json.dump(intent.data, f, indent=2)

# Logging handler
@sync_performer
def info_performer(_, intent: Info):
    logging.info(intent.msg)

@sync_performer
def error_performer(_, intent: Error):
    logging.error(intent.msg)

# Concurrency handler (simplified)
global_lock = threading.Lock()

@sync_performer
def with_lock_performer(_, intent: WithLock):
    with global_lock:
        return intent.fn()
```

Compose them:

```python
dispatcher = ComposedDispatcher({
    Load: load_performer,
    Save: save_performer,
    Info: info_performer,
    Error: error_performer,
    WithLock: with_lock_performer,
})
```

Running the program:

```python
if __name__ == "__main__":
    # All effects are resolved by the dispatcher
    result = dispatcher.run(lambda: add_todo("Buy milk", "todos.json"))
    print("Current list:", result)
```

### 6️⃣ Benefits Observed

* **Testability** – Replace `Load`/`Save` with in‑memory mocks; the same `add_todo` works unchanged.
* **Extensibility** – Add a new effect `Audit` without touching core logic; just plug a new handler.
* **Clarity** – The business function reads like a narrative: *load, modify, save, log*.

## Benefits and Trade‑offs

### Advantages

1. **Separation of Concerns** – Logic declares *what* it needs; handlers decide *how* to provide it.
2. **Composable Handlers** – Multiple handlers can be stacked or scoped, enabling layered concerns (e.g., logging + tracing).
3. **First‑Class Continuations** – Handlers receive the suspended continuation, allowing advanced control flow such as backtracking, coroutines, or retry policies.
4. **Improved Testability** – Mock handlers replace real side effects with deterministic behavior.

### Potential Drawbacks

| Issue | Explanation | Mitigation |
|-------|-------------|------------|
| **Runtime Support** | Not all languages have built‑in effect systems; you need a library or compiler extension. | Choose a language with mature support (e.g., **OCaml**, **Koka**, **Eff**, **Multicore OCaml**, **Scala 3** with `effect` plugin). |
| **Performance Overhead** | Capturing continuations incurs allocation; naive implementations may be slower than direct calls. | Use optimized runtimes (e.g., Multicore OCaml’s effect handlers) or compile‑time effect elimination. |
| **Learning Curve** | Developers accustomed to monads or callbacks need to understand effect‑handler semantics. | Provide clear documentation and small reference implementations. |
| **Debugging Complexity** | Stack traces can be fragmented across handler boundaries. | Leverage tooling that prints effect traces (e.g., `ocaml-effect` debugger). |

## Implementations in Modern Languages

| Language | Library / Feature | Notable Projects |
|----------|-------------------|-------------------|
| **OCaml** | Native effect handlers (Multicore OCaml) | `Eio` I/O library, `Lwt` integration |
| **Koka** | Built‑in algebraic effects | The Koka compiler itself |
| **Eff** | Dedicated language for effects | Research prototypes, educational material |
| **Scala 3** | `Effect` trait via the `dotty` compiler plugin | ZIO, Cats‑Effect (though ZIO uses a different model) |
| **Rust** | `effectful` crate (experimental) | Community prototypes for async I/O |
| **Python** | `effect` library, `trio`‑style task groups (conceptually similar) | The example above |

### Example: OCaml’s `Eio` Library

```ocaml
open Eio.Std

let read_line () =
  let* line = Eio.Console.read_line stdin in
  Fiber.return line

let greet_user () =
  let* name = read_line () in
  Eio.Console.printlf stdout "Hello, %s!" name
```

`Eio` uses *effects* (`await`‑like) under the hood, allowing the same `greet_user` function to run on top of different schedulers (threads, async I/O, or mock environments) without modification.

## Key Takeaways

- **Algebraic effects** let you declare *abstract operations* separate from their implementation, turning effectful calls into first‑class suspensions.
- **Handlers** provide concrete semantics, can manipulate continuations, and can be scoped locally for testing or specialization.
- Decoupling logic using effects yields **cleaner, more modular code** that is easier to test, extend, and reason about.
- The approach requires **runtime or compiler support**, but several modern languages (OCaml, Koka, Eff, Scala 3) already ship with robust implementations.
- When performance matters, prefer **native effect handlers** (e.g., Multicore OCaml) over library‑level emulations.

## Further Reading

- [Algebraic Effects and Handlers – Plotkin & Pretnar (2009)](https://dl.acm.org/doi/10.1145/1596550.1596560)  
- [OCaml Multicore Effects Documentation](https://ocaml.org/manual/multicore.html)  
- [Koka Language – Effect Handlers Overview](https://koka-lang.github.io/koka/doc/handlers.html)  
- [Eff – A Language for Algebraic Effects](https://eff-lang.org/)  
- [Eio – Effects‑Based I/O for OCaml](https://github.com/ocaml-multicore/eio)  