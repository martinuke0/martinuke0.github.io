---
title: "A Detailed Guide to Python __slots__: Memory, Performance, and Pitfalls"
date: "2025-12-26T16:29:05.411"
draft: false
tags: ["python", "performance", "memory", "slots", "oop"]
---

Python gives you a lot of flexibility with objects—but that flexibility comes at a cost. Instances normally carry a per-object dictionary to store attributes, which is powerful but memory‑hungry and a bit slower than it could be.

`__slots__` is a mechanism that lets you trade some of that flexibility for:

- Lower memory usage per instance
- Slightly faster attribute access
- A fixed, enforced set of attributes

This article is a detailed, practical guide to `__slots__`: how it works, when it helps, when it hurts, and how to use it correctly in modern Python.

---

## Table of Contents

1. [What Problem Does `__slots__` Solve?](#what-problem-does-__slots__-solve)
2. [How Python Normally Stores Attributes](#how-python-normally-stores-attributes)
3. [Basic Usage of `__slots__`](#basic-usage-of-__slots__)
   - [Defining slots](#defining-slots)
   - [What changes for instances](#what-changes-for-instances)
4. [Memory Savings in Practice](#memory-savings-in-practice)
5. [Performance Characteristics](#performance-characteristics)
6. [Detailed Semantics and Rules](#detailed-semantics-and-rules)
   - [Valid `__slots__` definitions](#valid-__slots__-definitions)
   - [Inheritance rules](#inheritance-rules)
   - [Class attributes vs slots](#class-attributes-vs-slots)
   - [Default values with slots](#default-values-with-slots)
7. [Limitations and Gotchas](#limitations-and-gotchas)
   - [No `__dict__` by default](#no-__dict__-by-default)
   - [Weak references and `__weakref__`](#weak-references-and-__weakref__)
   - [Multiple inheritance](#multiple-inheritance)
   - [Pickling slotted classes](#pickling-slotted-classes)
   - [Introspection differences](#introspection-differences)
8. [`__slots__` with Dataclasses and Modern Tools](#__slots__-with-dataclasses-and-modern-tools)
9. [When You Should (and Shouldn’t) Use `__slots__`](#when-you-should-and-shouldnt-use-__slots__)
10. [Common Misconceptions](#common-misconceptions)
11. [Conclusion](#conclusion)

---

## What Problem Does `__slots__` Solve?

In CPython, each normal object instance contains:

- A header (reference count, type pointer, etc.)
- A pointer to a per-instance `__dict__` used to store attributes

That per-instance dictionary is *flexible*, but expensive:

- It uses extra memory
- It adds indirection to attribute access

For many use cases (configuration objects, small data containers, etc.), you don’t need dynamic attributes. All instances of your class have the same fixed fields like `x`, `y`, and `z`. In those cases, `__slots__` can reduce memory and give you slightly faster attribute access by:

- Replacing the per-instance attribute dictionary
- Allocating space for a fixed set of attributes directly in the instance’s internal structure

> **Key idea**: `__slots__` is mostly about **memory layout** and **attribute control**, not magic performance boosts for arbitrary code.

---

## How Python Normally Stores Attributes

Consider a simple class:

```python
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
```

Each `Point` instance gets its own `__dict__`:

```python
p = Point(1, 2)
print(p.__dict__)  # {'x': 1, 'y': 2}

p.z = 3
print(p.__dict__)  # {'x': 1, 'y': 2, 'z': 3}
```

This dictionary:

- Lives per instance
- Can grow and shrink at runtime
- Can store any new attribute you assign

That flexibility is nice, but you pay for it in extra memory overhead per object.

---

## Basic Usage of `__slots__`

### Defining slots

To use slots, define a `__slots__` attribute at the class level:

```python
class Point:
    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x = x
        self.y = y
```

Or with a list:

```python
class Point:
    __slots__ = ["x", "y"]
```

Or even a single string (less common, but valid):

```python
class Point:
    __slots__ = "x", "y"  # same as ("x", "y")
```

Each name in `__slots__` is:

- A *slot name*
- Corresponds to a low-level storage slot in the instance

### What changes for instances

With `__slots__` defined like this:

```python
p = Point(1, 2)

# Allowed:
p.x = 10
p.y = 20

# Not allowed (not in __slots__):
p.z = 30  # AttributeError
```

You’ll see some differences:

```python
p = Point(1, 2)

# This now raises AttributeError:
try:
    print(p.__dict__)
except AttributeError as e:
    print(e)  # 'Point' object has no attribute '__dict__'
```

The instance no longer has a `__dict__` by default, which is where much of the memory savings come from.

---

## Memory Savings in Practice

The actual savings depend on:

- Your Python implementation (CPython vs PyPy, etc.)
- How many instances you create
- How many attributes you store

Here’s a simple CPython example to illustrate:

```python
import sys

class NormalPoint:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class SlottedPoint:
    __slots__ = ("x", "y")
    def __init__(self, x, y):
        self.x = x
        self.y = y

normal = [NormalPoint(i, i) for i in range(10_000)]
slotted = [SlottedPoint(i, i) for i in range(10_000)]

print(sys.getsizeof(normal[0]))   # size of a single instance
print(sys.getsizeof(slotted[0]))
```

`sys.getsizeof` **does not include the size of the instance’s `__dict__`**, so the numbers for `NormalPoint` can be misleading. To get a more realistic measurement, you need a tool that can consider the reachable object graph, such as `pympler`:

```python
from pympler import asizeof

print(asizeof.asizeof(normal[0]))
print(asizeof.asizeof(slotted[0]))
```

You’ll typically see that slotted instances use significantly less memory (often 30–60% less for small data objects).

> **Rule of thumb**: `__slots__` becomes worthwhile when you’ll have **many** instances (thousands or more) of the same small class.

---

## Performance Characteristics

Attribute access with `__slots__` can be a bit faster because:

- Python skips the dictionary lookup for attribute storage
- It uses a fixed offset in the instance’s layout

But:

- The speedup is usually modest (single‑digit percentage improvements)
- Memory savings are generally more meaningful than speed

A simple benchmark (do not rely on this for production decisions; always test your own workloads):

```python
import timeit

setup = """
class NormalPoint:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class SlottedPoint:
    __slots__ = ("x", "y")
    def __init__(self, x, y):
        self.x = x
        self.y = y

normal = NormalPoint(1, 2)
slotted = SlottedPoint(1, 2)
"""

normal_get = "normal.x"
slotted_get = "slotted.x"

print("Normal:", timeit.timeit(normal_get, setup=setup, number=10_000_00))
print("Slotted:", timeit.timeit(slotted_get, setup=setup, number=10_000_00))
```

Expect modest improvements. In many applications, this will not be the bottleneck.

---

## Detailed Semantics and Rules

### Valid `__slots__` definitions

`__slots__` can be:

- A string (for a single slot)
- A sequence of strings (tuple, list, etc.)
- An iterable evaluated at class creation time

Examples:

```python
class A:
    __slots__ = "x"  # single attribute

class B:
    __slots__ = ("x", "y")

class C:
    fields = ["x", "y", "z"]
    __slots__ = fields  # uses the list

class D:
    __slots__ = (*("x", "y"), "z")  # any expression that yields an iterable of strings
```

Slot names must be valid attribute names (identifiers) in almost all practical cases.

### Inheritance rules

Inheritance with `__slots__` is a common source of confusion. There are several key cases:

#### 1. Base class has no `__slots__`, subclass defines them

```python
class Base:
    pass

class Sub(Base):
    __slots__ = ("x", "y")
```

Instances of `Sub` **still get a `__dict__`** because `Base` has one. Slots are used for `x` and `y`, but you can still add arbitrary attributes via the inherited `__dict__`:

```python
s = Sub()
s.x = 1
s.z = 3  # works; stored in __dict__
print(s.__dict__)  # {'z': 3}
```

> If any class in the inheritance chain has no `__slots__`, instances will have a `__dict__` unless you take extra care.

#### 2. Base class defines `__slots__`, subclass does not

```python
class Base:
    __slots__ = ("x", "y")

class Sub(Base):
    pass
```

`Sub` inherits the slots from `Base` and **does not** gain a `__dict__` just because it doesn’t define `__slots__`. Instances of `Sub` have the same slot-based layout as `Base`:

```python
s = Sub()
s.x = 1
# s.z = 3  # AttributeError
```

#### 3. Both base and subclass define `__slots__`

```python
class Base:
    __slots__ = ("x",)

class Sub(Base):
    __slots__ = ("y",)
```

Instances of `Sub` have slots for both `x` *and* `y`, and no `__dict__` by default.

#### 4. Using `__dict__` explicitly

If you want a class that primarily uses slots but **also** allows dynamic attributes, include `"__dict__"` in the slots:

```python
class Mixed:
    __slots__ = ("x", "y", "__dict__")

m = Mixed()
m.x = 1
m.z = 3  # allowed, stored in m.__dict__
```

This gives you:

- Fixed, fast slots for certain attributes
- A regular dictionary for extra attributes

### Class attributes vs slots

Class attributes and slots are different concepts:

```python
class Foo:
    __slots__ = ("x",)
    x = 1  # class attribute
```

Here:

- `Foo.x` is a class attribute
- `Foo().__dict__` doesn’t exist
- `Foo()` instances have a per-instance slot named `x`

Attribute resolution works as normal:

1. Per-instance storage (slots, then instance dict if present)
2. Class attributes
3. Base classes

If you set an instance attribute:

```python
f = Foo()
f.x = 2  # stored in the 'x' slot, hiding the class attribute
```

The class-level default is often used only until you assign a value in the instance’s slot.

### Default values with slots

`__slots__` does not provide default values. Common patterns:

1. Use class attributes as defaults:

   ```python
   class Point:
       __slots__ = ("x", "y")
       x = 0
       y = 0

       def __init__(self, x=None, y=None):
           if x is not None:
               self.x = x
           if y is not None:
               self.y = y
   ```

2. Set defaults in `__init__`:

   ```python
   class Point:
       __slots__ = ("x", "y")

       def __init__(self, x=0, y=0):
           self.x = x
           self.y = y
   ```

---

## Limitations and Gotchas

### No `__dict__` by default

With pure `__slots__` (no `"__dict__"` in the list), instances:

- Do **not** have `__dict__`
- Cannot accept arbitrary new attributes

This breaks some patterns that rely on dynamic attributes:

```python
class Config:
    __slots__ = ("host", "port")

c = Config()
c.host = "localhost"
c.port = 5432

# Later someone tries:
c.debug = True  # AttributeError
```

Some libraries and tools implicitly assume objects have a `__dict__`. Examples:

- Some serializers or ORMs
- Some generic debugging / inspection utilities

You can work around this by adding `"__dict__"` to slots if you need both capabilities.

### Weak references and `__weakref__`

Normal instances can be weakly referenced:

```python
import weakref

class A:
    pass

a = A()
r = weakref.ref(a)  # works
```

Slotted instances **cannot** be weakly referenced unless you include `"__weakref__"` in `__slots__`:

```python
class B:
    __slots__ = ("x", "__weakref__")

b = B()
r = weakref.ref(b)  # now works
```

> If instances of your class might be used with `weakref`, always include `"__weakref__"` in `__slots__`.

### Multiple inheritance

Multiple inheritance with `__slots__` can be tricky and should be approached with care.

Rules (simplified):

- All slotted base classes must be compatible
- If two base classes define the same slot name, that is usually an error
- If some base classes have `__dict__` and others don’t, you can get surprising layouts

Example of a conflict:

```python
class A:
    __slots__ = ("x",)

class B:
    __slots__ = ("x",)  # same name as in A

class C(A, B):
    __slots__ = ()  # TypeError at class creation in CPython
```

In practice:

- Avoid complex multiple inheritance hierarchies with `__slots__`
- Prefer composition or mixins that **do not** use `__slots__`
- Use small, well-contained hierarchies if you must combine them

### Pickling slotted classes

Pickling normally works if:

- The class is defined at the module top level
- **Or** the class provides appropriate `__getstate__` / `__setstate__` or `__reduce__`

For slotted classes **without** a `__dict__`, Python uses slot descriptors to reconstruct the instance. But some tools assume `__dict__` exists.

To be explicit and robust, you can define:

```python
import pickle

class Point:
    __slots__ = ("x", "y")

    def __getstate__(self):
        return (self.x, self.y)

    def __setstate__(self, state):
        self.x, self.y = state

p = Point()
p.x = 1
p.y = 2

data = pickle.dumps(p)
p2 = pickle.loads(data)
```

If your class includes `"__dict__"` in slots, pickling generally behaves closer to normal classes.

### Introspection differences

Many introspection patterns rely on `__dict__`. For slotted objects:

- `obj.__dict__` may not exist
- `vars(obj)` raises `TypeError` unless you’ve added `"__dict__"`

Better, more general patterns:

- Use `dir(obj)` to list attributes
- Use `getattr(obj, name, default)` to query
- Use `hasattr(obj, "__dict__")` to see if instances are dict-backed

---

## `__slots__` with Dataclasses and Modern Tools

Modern Python provides higher‑level tools that integrate with `__slots__`.

### Slotted dataclasses (Python 3.10+)

Dataclasses gained native slot support in Python 3.10 via the `slots=True` parameter:

```python
from dataclasses import dataclass

@dataclass(slots=True)
class Point:
    x: int
    y: int
```

Benefits:

- Automatically creates `__slots__` for all fields
- Keeps type annotations and dataclass features
- More ergonomic than hand-writing `__slots__`

Caveats:

- The dataclass will not have a `__dict__` by default
- If you use tools that expect instances to be dict-backed, add `unsafe_hash=True` or adjust patterns as needed (depending on your use case)

### `attrs` and other libraries

Libraries like `attrs` and Pydantic also support slotted classes:

- **attrs**:

  ```python
  import attrs

  @attrs.define(slots=True)
  class Point:
      x: int
      y: int
  ```

- **Pydantic** (v1 has `Config` options; v2 uses different patterns), often focusing on performance and memory as well.

These tools handle much of the boilerplate for you and are preferable to hand-written slot management for complex models.

---

## When You Should (and Shouldn’t) Use `__slots__`

### Good candidates for `__slots__`

Use `__slots__` when:

1. **You create many instances** of a class  
   For example, millions of small objects in:

   - Simulations
   - Parsers / compilers
   - In-memory caches
   - Data processing pipelines

2. **The set of attributes is fixed**  
   Instances won’t need arbitrary new attributes added dynamically.

3. **You control both the class and its usage**  
   You know how the class will be used and by whom (e.g., internal library code).

### When to avoid `__slots__`

Think twice or avoid when:

1. **You’re designing flexible, user-extensible APIs**  
   Users might reasonably expect to attach attributes (e.g., `.metadata` or `.debug_info`).

2. **You rely heavily on reflection / dynamic behavior**  
   If your code or third-party libraries enumerate or modify `__dict__`, slots can break assumptions.

3. **You don’t have a real memory problem**  
   The complexity cost isn’t worth it if you’re not actually constrained.

4. **You have complex multiple inheritance hierarchies**  
   Interactions can be subtle, and bugs are hard to diagnose.

> A sensible policy:  
> Apply `__slots__` **surgically** to well-understood, internal data classes where profiling has shown a real benefit.

---

## Common Misconceptions

### “`__slots__` always makes my code faster”

Not necessarily. The main benefit is **memory**. Speedups in attribute access are modest and often irrelevant compared to I/O, algorithmic complexity, or database calls.

### “`__slots__` turns my class into a C struct”

It changes the memory layout in CPython, but your object is still a Python object with all the usual semantics: garbage collection, dynamic dispatch, etc.

### “I can’t use `__slots__` and still allow extra attributes”

You can, by including `"__dict__"` in the slots:

```python
class Flexible:
    __slots__ = ("x", "__dict__")
```

This allows:

- `x` stored in a slot
- Any other attribute stored in `__dict__`

### “All classes in an inheritance tree must use `__slots__` or none can”

Partial use is allowed. The reality is:

- If any base class has a `__dict__`, instances will have one (unless very carefully arranged)
- Slot-only hierarchies are possible but require more discipline

---

## Conclusion

`__slots__` is a powerful but low-level tool in Python’s object model. Used thoughtfully, it can:

- Cut memory usage for large numbers of small objects
- Slightly speed up attribute access
- Enforce a fixed set of instance attributes

However, it also:

- Removes per-instance `__dict__` by default
- Introduces complexity with inheritance and some libraries
- Offers limited performance improvements outside of specific patterns

Guidelines to keep in mind:

- **Start without `__slots__`**. Write clear, idiomatic code first.
- **Profile your application**. Only introduce `__slots__` where memory is actually a concern.
- **Prefer higher-level tools** (dataclasses with `slots=True`, `attrs`, etc.) when possible.
- **Be explicit about trade-offs** in library code, especially public APIs.

Understanding how `__slots__` changes the memory layout and attribute model will help you decide when it’s the right tool—and when you should reach for something simpler.