---
title: "Events in Python: A Deep, Unforgettable Guide to Event-Driven Thinking"
date: "2025-12-07T20:54:56.78"
draft: false
tags: ["python", "events", "asyncio", "design-patterns", "architecture"]
---

## Introduction

Imagine a doorbell. You press it (something happens), the chime sounds (a reaction happens), and perhaps a camera starts recording (another reaction). You don’t call the chime function directly. You signal that “an event occurred,” and any number of listeners react.

That’s the core of events in software: something happens, interested parties respond. Events are everywhere—GUI buttons, network sockets becoming readable, a file changing, a business action like “order_placed,” or a job finishing. In Python, you can use events via libraries (Tkinter, Qt, asyncio, Django signals), operating-system interfaces (selectors), or create your own event systems.

This article will take you deep into events in Python—how to think about them so you never forget, and how to implement them correctly, synchronously and asynchronously, with practical code examples and mental models that stick.

> Memory hook: Events decouple “what happened” from “who cares.” Emitters announce. Listeners react.

If you’re comfortable writing functions and classes but want a rock-solid mental model for event-driven programming, this guide is for you.

## Table of Contents

- [What Are Events? A Mental Model You Won’t Forget](#what-are-events-a-mental-model-you-wont-forget)
- [Anatomy of an Event System](#anatomy-of-an-event-system)
- [Synchronous Events in Pure Python (Observer Pattern)](#synchronous-events-in-pure-python-observer-pattern)
  - [A Minimal EventBus](#a-minimal-eventbus)
  - [Improvements: once-handlers, priorities, and weak references](#improvements-once-handlers-priorities-and-weak-references)
- [Asynchronous Events with asyncio](#asynchronous-events-with-asyncio)
  - [Two Meanings: asyncio.Event vs “application events”](#two-meanings-asyncioevent-vs-application-events)
  - [Example: Coordination with asyncio.Event](#example-coordination-with-asyncioevent)
  - [Example: Async Publish/Subscribe with asyncio.Queue](#example-async-publishsubscribe-with-asyncioqueue)
- [GUI Events in Tkinter (and the Idea of Binding)](#gui-events-in-tkinter-and-the-idea-of-binding)
- [Low-Level I/O Readiness Events with selectors](#low-level-io-readiness-events-with-selectors)
- [Domain Events and Framework Signals (Django)](#domain-events-and-framework-signals-django)
- [Testing Event-Driven Code](#testing-event-driven-code)
- [Pitfalls and Best Practices](#pitfalls-and-best-practices)
- [Recap: The 7 Rules You’ll Never Forget](#recap-the-7-rules-youll-never-forget)
- [Conclusion](#conclusion)

## What Are Events? A Mental Model You Won’t Forget

- An event is a fact: “X happened.”
- Listeners care about specific facts and react.
- The emitter doesn’t know who listens; it just broadcasts.
- This decoupling allows you to add, remove, or modify reactions without changing the code that emits the event.

Another mental hook: newsroom alerts.
- An alert goes on the wire (“breaking_news: …”).
- Different desks react: the website updates, push notifications go out, social media posts are queued.
- The alert doesn’t know who will act. It just states the fact.

## Anatomy of an Event System

- Event name (topic/type): a string or enum, e.g., "user_registered".
- Payload: supplementary data, e.g., {"user_id": 123}.
- Emitter/dispatcher: code that announces the event.
- Listener/handler: a function (sync or async) that reacts.
- Event loop/queue (optional): buffers events, schedules handlers.
- Policies: error handling, ordering, backpressure, threading model.

In Python, you can build these pieces yourself or use existing frameworks. Let’s start with a simple, synchronous approach.

## Synchronous Events in Pure Python (Observer Pattern)

### A Minimal EventBus

Below is a tiny yet practical EventBus supporting subscribe, unsubscribe, and emit. It’s synchronous: handlers run immediately in the emitter’s call stack.

```python
from collections import defaultdict
from typing import Callable, Dict, List, Any

class EventBus:
    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable[..., None]]] = defaultdict(list)

    def on(self, event: str, handler: Callable[..., None]) -> None:
        """Register a handler for a named event."""
        self._handlers[event].append(handler)

    def off(self, event: str, handler: Callable[..., None]) -> None:
        """Unregister a handler."""
        try:
            self._handlers[event].remove(handler)
        except (KeyError, ValueError):
            pass  # silently ignore

    def emit(self, event: str, **payload: Any) -> None:
        """Emit an event synchronously; handlers run now."""
        for handler in list(self._handlers.get(event, [])):
            try:
                handler(**payload)
            except Exception as e:
                # In production, log the error; don't let one handler crash all
                print(f"Handler error for event '{event}': {e}")

# Usage
bus = EventBus()

def log_signup(user_id: int) -> None:
    print(f"[log] user signed up: {user_id}")

def send_welcome_email(user_id: int) -> None:
    print(f"[email] welcome user {user_id}")

bus.on("user_signed_up", log_signup)
bus.on("user_signed_up", send_welcome_email)

bus.emit("user_signed_up", user_id=42)
```

Output:
- [log] user signed up: 42
- [email] welcome user 42

Key ideas:
- The emitter doesn’t know who’s listening—only that “user_signed_up” happened.
- The payload is kwargs; handlers must accept those names.
- Errors are isolated per handler so one faulty listener doesn’t break all.

> Note: Synchronous emit means if a handler is slow, your emitter is slow. This is okay for small-scale desktop code or where event handlers are cheap.

### Improvements: once-handlers, priorities, and weak references

Production-grade event systems often need:
- “Once” handlers that auto-unsubscribe after first run
- Priorities for ordering
- Weak references to avoid memory leaks (handlers owning the bus or vice versa)

Here’s an extended version:

```python
import weakref
from dataclasses import dataclass, field
from typing import Callable, Any, Dict, List, Optional

@dataclass(order=True)
class _Listener:
    priority: int
    handler_ref: Any = field(compare=False)
    once: bool = field(default=False, compare=False)

class EventBusPro:
    def __init__(self) -> None:
        self._handlers: Dict[str, List[_Listener]] = {}

    def on(self, event: str, handler: Callable[..., None], *, priority: int = 0) -> None:
        self._register(event, handler, once=False, priority=priority)

    def once(self, event: str, handler: Callable[..., None], *, priority: int = 0) -> None:
        self._register(event, handler, once=True, priority=priority)

    def off(self, event: str, handler: Callable[..., None]) -> None:
        if event not in self._handlers:
            return
        self._handlers[event] = [
            l for l in self._handlers[event]
            if l.handler_ref() is not handler
        ]

    def emit(self, event: str, **payload: Any) -> None:
        listeners = sorted(self._handlers.get(event, []))  # sort by priority
        to_remove: List[_Listener] = []

        for listener in listeners:
            func = listener.handler_ref()
            if func is None:
                to_remove.append(listener)
                continue
            try:
                func(**payload)
            except Exception as e:
                print(f"[warn] handler error in '{event}': {e}")
            if listener.once:
                to_remove.append(listener)

        if to_remove:
            self._handlers[event] = [
                l for l in self._handlers.get(event, []) if l not in to_remove
            ]

    def _register(self, event: str, handler: Callable[..., None], *, once: bool, priority: int) -> None:
        # Use weak references to avoid preventing garbage collection of bound methods
        if hasattr(handler, "__self__") and handler.__self__ is not None:
            ref = weakref.WeakMethod(handler)  # bound method
        else:
            ref = weakref.ref(handler)  # function
        self._handlers.setdefault(event, []).append(_Listener(priority=priority, handler_ref=ref, once=once))

# Example
bus = EventBusPro()

class Greeter:
    def hello(self, name: str):
        print(f"Hello, {name}!")

g = Greeter()
bus.on("greet", g.hello, priority=10)
bus.once("greet", lambda name: print(f"(once) Welcome, {name}!"))

bus.emit("greet", name="Ada")
bus.emit("greet", name="Grace")
```

This model:
- Respects ordering via priorities.
- Avoids leaks by weakly referencing bound methods; if `g` is deleted, its handler disappears.
- Supports `once` semantics.

## Asynchronous Events with asyncio

### Two Meanings: asyncio.Event vs “application events”

Be careful: “event” in asyncio has two distinct meanings.

1) asyncio.Event: a low-level synchronization primitive like a threading.Event. It’s a boolean flag to coordinate tasks (set/wait/clear). It does not carry payloads or multiple listeners by itself.

2) Application events: domain messages like "price_updated" with handlers. In async code, you often implement these using queues or topic buses and deliver to async handlers.

### Example: Coordination with asyncio.Event

Use this when tasks need to wait for a condition.

```python
import asyncio

async def worker(ready: asyncio.Event):
    print("Worker waiting for readiness...")
    await ready.wait()  # suspend until set()
    print("Worker sees ready flag; starting work...")
    await asyncio.sleep(0.5)
    print("Worker finished.")

async def main():
    ready = asyncio.Event()
    task = asyncio.create_task(worker(ready))
    await asyncio.sleep(1)  # simulate setup
    print("Setting ready flag.")
    ready.set()  # all current/future waiters proceed
    await task

asyncio.run(main())
```

Key points:
- asyncio.Event is for coordination, not broadcasting payloads.
- Multiple waiters can block until the event is set.
- You can call `ready.clear()` to reuse the flag.

### Example: Async Publish/Subscribe with asyncio.Queue

For application-level events with payloads and many listeners, a simple pattern uses topics mapped to queues. Each listener consumes messages asynchronously.

```python
import asyncio
from collections import defaultdict
from typing import Any, Dict, List, Callable, Awaitable

class AsyncEventBus:
    def __init__(self) -> None:
        self._subs: Dict[str, List[Callable[..., Awaitable[None]]]] = defaultdict(list)

    def on(self, event: str, handler: Callable[..., Awaitable[None]]) -> None:
        self._subs[event].append(handler)

    async def emit(self, event: str, **payload: Any) -> None:
        # schedule all handlers concurrently
        coros = []
        for handler in list(self._subs.get(event, [])):
            try:
                coros.append(handler(**payload))
            except TypeError as e:
                # handler signature mismatch
                print(f"[warn] handler mismatch for {event}: {e}")
        # Guard: don't fail if one raises
        results = await asyncio.gather(*coros, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                print(f"[warn] handler raised: {r}")

# Example usage
async def audit(user_id: int):
    await asyncio.sleep(0.1)
    print(f"[audit] user {user_id}")

async def notify(user_id: int):
    await asyncio.sleep(0.2)
    print(f"[notify] user {user_id}")

async def main():
    bus = AsyncEventBus()
    bus.on("user_signed_up", audit)
    bus.on("user_signed_up", notify)
    await bus.emit("user_signed_up", user_id=7)

asyncio.run(main())
```

This model:
- Lets handlers run concurrently using `asyncio.gather`.
- Handles exceptions per handler.
- Keeps the emitter responsive.

If you need backpressure or durable queues, consider `asyncio.Queue` per topic with dedicated consumer tasks:

```python
import asyncio
from collections import defaultdict
from typing import Any, Callable, Awaitable, Dict, List

class QueueBus:
    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._consumers: Dict[str, List[asyncio.Task]] = defaultdict(list)
        self._handlers: Dict[str, List[Callable[..., Awaitable[None]]]] = defaultdict(list)

    def on(self, event: str, handler: Callable[..., Awaitable[None]], *, consumers: int = 1) -> None:
        self._handlers[event].append(handler)
        # Launch consumers if not already
        while len(self._consumers[event]) < consumers:
            t = asyncio.create_task(self._consume(event))
            self._consumers[event].append(t)

    async def emit(self, event: str, **payload: Any) -> None:
        await self._queues[event].put(payload)  # backpressure if full

    async def _consume(self, event: str) -> None:
        q = self._queues[event]
        while True:
            payload = await q.get()
            try:
                # fan-out to all handlers per message
                await asyncio.gather(*(h(**payload) for h in self._handlers[event]), return_exceptions=False)
            except Exception as e:
                print(f"[warn] error handling {event}: {e}")
            finally:
                q.task_done()

# Example
async def handle_order(order_id: str):
    await asyncio.sleep(0.1)
    print(f"Processed order {order_id}")

async def main():
    bus = QueueBus()
    bus.on("order_created", handle_order, consumers=2)
    await asyncio.gather(*(bus.emit("order_created", order_id=str(i)) for i in range(5)))
    # wait until all processed
    await bus._queues["order_created"].join()

asyncio.run(main())
```

Here:
- Each topic has a queue; consumer tasks pull messages and run handlers.
- Natural backpressure: if producers outpace consumers, emit waits (unless you configure maxsize).
- This pattern resembles message brokers on a smaller scale.

## GUI Events in Tkinter (and the Idea of Binding)

GUI programming is inherently event-driven. You bind a handler to an event (like a click), and the GUI framework’s event loop calls your handler when the user acts.

```python
import tkinter as tk

def on_click():
    print("Button clicked!")

root = tk.Tk()
root.title("Events Demo")

btn = tk.Button(root, text="Click me", command=on_click)  # command is an event handler
btn.pack(padx=20, pady=20)

# Bind a keyboard event to the root window
def on_key(event):
    print(f"Key pressed: {event.keysym}")

root.bind("<Key>", on_key)

root.mainloop()  # enters the GUI event loop
```

Concepts:
- The framework runs an event loop (`mainloop`) that waits for OS events (mouse, keyboard).
- You “bind” handlers to event types or widgets.
- The event object (like in `on_key`) carries payload: which key, modifiers, etc.

> Remember: GUIs awaken only when users act. Your job is to bind the “reactions” and let the loop do the driving.

## Low-Level I/O Readiness Events with selectors

At the OS level, network sockets and files become “readable” or “writable.” Python’s `selectors` module lets you multiplex many sockets using event notifications.

```python
import socket
import selectors

sel = selectors.DefaultSelector()

def accept(sock):
    conn, addr = sock.accept()
    conn.setblocking(False)
    print("Accepted", addr)
    sel.register(conn, selectors.EVENT_READ, read)

def read(conn):
    data = conn.recv(1024)
    if data:
        conn.sendall(b"Echo: " + data)
    else:
        print("Closing", conn.getpeername())
        sel.unregister(conn)
        conn.close()

# Setup listening socket
lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
lsock.bind(("127.0.0.1", 9000))
lsock.listen()
lsock.setblocking(False)
sel.register(lsock, selectors.EVENT_READ, accept)

print("Echo server on 127.0.0.1:9000")
while True:
    for key, mask in sel.select():  # blocks until OS signals readiness
        callback = key.data
        sock = key.fileobj
        callback(sock)
```

This is the foundation for async frameworks. `asyncio` builds atop such mechanisms to give you coroutines rather than callbacks.

## Domain Events and Framework Signals (Django)

Web frameworks often provide signaling systems. In Django, “signals” are events. You connect receivers to signals to react to actions (save, delete, login, etc.).

```python
# apps.py
from django.apps import AppConfig

class UsersConfig(AppConfig):
    name = "users"

    def ready(self):
        from . import receivers  # ensure receivers are imported and connected
```

```python
# receivers.py
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.contrib.auth.models import User

@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        print(f"New user created: {instance.username} -> create profile here")
```

When a `User` is saved with `created=True`, Django emits `post_save`, and your receiver runs. It’s the same pattern: emitter (Django’s model layer) broadcasts a fact; your code listens.

## Testing Event-Driven Code

Patterns to keep tests deterministic:

- Synchronous bus: emit and assert side-effects immediately.
- Async bus: use `asyncio.run` or a test runner’s event loop (pytest-asyncio) and await completion.
- Spies/mocks: assert that particular handlers were called with expected payloads.
- Timeouts: when waiting for events, always use timeouts to avoid hanging tests.

Example with asyncio and a spy:

```python
import asyncio

called = []

async def handler(x: int):
    called.append(x)

async def test_bus():
    bus = AsyncEventBus()
    bus.on("x", handler)
    await bus.emit("x", x=5)
    assert called == [5]

asyncio.run(test_bus())
```

## Pitfalls and Best Practices

- Don’t let handlers crash the world:
  - Wrap handler execution; log and continue.
  - In asyncio, use `gather(..., return_exceptions=True)` when fanning out.

- Backpressure matters:
  - If events can outpace consumers, choose a queue with bounded size or drop/overflow policy.
  - Use `asyncio.Queue(maxsize=n)` to apply natural backpressure.

- Avoid hidden coupling:
  - Keep event names stable and documented.
  - Prefer typed payloads or data classes to avoid fragile kwargs.

- Memory leaks with listeners:
  - If listeners are bound methods, use weak references or provide clear unsubscribe.
  - Offer `once` handlers for fire-and-forget cases.

- Ordering guarantees:
  - Define whether handlers run in registration order, priority order, or concurrently.
  - Document it; tests should assert it.

- Threading vs async:
  - Don’t call UI frameworks from background threads; marshal to the main thread/event loop.
  - In mixed environments, use thread-safe queues or loop.call_soon_threadsafe.

- Name collisions and wildcards:
  - Namespaces help: "user.signed_up" vs "user.deleted".
  - If you need wildcard subscription, standardize and implement carefully (e.g., prefix matching).

- Distinguish control vs data events:
  - asyncio.Event is a control flag for coordination, not a data-carrying broadcast.

## Recap: The 7 Rules You’ll Never Forget

1) An event is a fact: “X happened,” not “do Y.”  
2) Emitters don’t know listeners. That’s the decoupling superpower.  
3) Payloads carry context; keep them stable and typed where possible.  
4) Synchronous events are simple but can block; asynchronous events scale better.  
5) asyncio.Event coordinates; queues and buses broadcast.  
6) Guard against handler failures, memory leaks, and overload.  
7) Document your event names and guarantees (ordering, concurrency, delivery).

If you remember nothing else: decouple with facts, deliver with discipline.

## Conclusion

Events are the connective tissue of responsive, modular systems. In Python, you can start small with a synchronous EventBus, grow into asyncio-based fan-out with proper backpressure, bind UI reactions in Tkinter, listen to low-level I/O readiness with selectors, and embrace framework-level signals like Django’s.

The unforgettable mental model: Emit facts; let interested parties react. Choose sync or async delivery based on the cost of handlers and throughput needs. Guard against failure, define your guarantees, and you’ll build systems that are both flexible and robust.

From doorbells to data centers, events let your code say, “This happened”—and let everything else happen because of it.