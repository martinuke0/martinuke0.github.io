---
title: "Inside the Lua VM: How the Reference Implementation Compiles and Executes Bytecode"
date: "2026-09-07T00:00:43.369"
draft: false
tags: ["lua", "virtual-machines", "bytecode", "interpreters", "language-implementation"]
description: "A guided tour of the Lua 5.4 reference VM, from source parsing to bytecode dispatch, with a look at how opcodes, registers, and the GC shape real-world behavior."
summary: "A walk through the reference Lua VM: lexing, parsing, code generation, and the register-based interpreter loop that makes Lua famously fast for a small footprint."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-inside-the-lua-vm-how-the-reference-implementation-compiles-and-executes-bytecode.svg"
  alt: "Annotated diagram of the Lua VM pipeline from source to bytecode execution."
  caption: ""
  relative: false
---

> **TL;DR** — The reference Lua VM is a register-based, single-pass compiler that turns source into a compact bytecode stream, then runs it through a portable interpreter loop using tagged-value registers. Understanding its pipeline explains why Lua is small, fast, and easy to embed — and why features like coroutines, generational GC, and the `LUAI_MAXSTACK` constant exist.

## Why the Lua VM Still Matters

Lua is the kind of language that hides in plain sight. It powers game scripting in Roblox, World of Warcraft add-ons, and Angry Birds; it sits inside Nginx as the OpenResty glue; it runs configuration and orchestration logic in Redis, Wireshark, and even parts of the Linux kernel build system. Almost everywhere you find it, you find the **reference implementation** — sometimes called PUC-Rio Lua after the Pontifical Catholic University of Rio de Janeiro where Roberto Ierusalimschy and his collaborators built it.

What makes the reference VM worth dissecting in 2026 is that it has stayed remarkably true to its design choices: a tiny C codebase, a register-based bytecode, and a portable interpreter that compiles and executes without needing a JIT compiler in the loop. Studying it is a masterclass in how to build a production-grade virtual machine that fits in roughly 17,000 lines of C and still benchmarks competitively with much larger runtimes.

This post walks through the full pipeline: how Lua goes from text on disk to a running program, what each opcode does, how the dispatch loop works, and where the GC and coroutine machinery fit in. Along the way we'll point at the actual source files in [the Lua source tree](https://www.lua.org/source/5.4/) so you can read along.

## The Pipeline at a Glance

Every `lua` or `luac` invocation runs the same high-level pipeline, implemented across a handful of source files in `src/`:

1. **Lexer** (`llex.c`) — turns source text into tokens.
2. **Parser** (`lparser.c`) — builds an abstract syntax tree of statements and expressions.
3. **Code generator** (`lcode.c`, called from the parser) — emits bytecode instructions as the parser descends.
4. **Function prototype** (`lfunc.c`) — packages bytecode plus constants and upvalue descriptors into a `Proto` object.
5. **Interpreter** (`lvm.c`) — executes the bytecode through a giant `switch`-based dispatch loop.
6. **Garbage collector** (`lgc.c`) — runs incrementally and generationally to reclaim memory.

The pipeline is **single-pass**: there is no separate AST traversal pass for code generation. As soon as the parser knows enough about a construct to emit valid bytecode, it does so immediately. This keeps the compiler fast and the memory footprint small — important for embedded targets where Lua often runs.

## From Source to Tokens

The lexer is a hand-written state machine. It does not use a table-driven DFA, regex engine, or generated scanner. Instead, `llex.c` contains a `lexstate` struct plus a `luaX_next` function that loops over characters, advancing a state variable that switches between modes such as normal code, long string `[=[ ... ]=]`, long comment, or numeric literal parsing.

A few details worth noting:

- **Numbers are scanned as either integers or floats** depending on whether an exponent or decimal point is present. The literal `1` is stored as an integer; `1.0` becomes a float. The lexer attaches a `TK_INT` or `TK_FLT` token type so the parser can choose the right codegen path. Lua 5.4 introduced this integer/float split, replacing Lua 5.3's number subtype.
- **Reserved words are looked up in a sorted array** (`llex.c` reserves the keyword list) using a binary search rather than a hash table — a micro-optimization that pays off given how often keywords appear.
- **Long strings and comments share the same `[-level-[ ... ]-level-]` syntax**. The `level` lets you nest comments, a feature unique to Lua that solves a real problem in C-style `/* */` comments.

The tokens emitted by `luaX_next` are fed into the parser through a recursive-descent entry point in `lparser.c`. There is no separate token buffer — the parser pulls one token at a time.

## Parsing and Incremental Codegen

`lparser.c` is one of the larger files in the tree, but conceptually it is a textbook recursive-descent parser with one twist: every time a production is recognized, the matching action emits one or more bytecode instructions.

For example, parsing the expression `a + b` produces something like:

```text
exp: primaryexp   -- 'a'
exp: primaryexp   -- 'b'
BINOP: OP_ADD
```

By the time the parser has consumed `a`, it has already emitted an `OP_MOVE` or `OP_GETTABUP` to load `a` into the current "base register" slot. By the time it has consumed `b`, it has emitted a second load into the next slot. Finally, it calls `luaK_codeABC` to emit a single three-operand `OP_ADD` instruction that adds register `k` to register `j` and stores the result in register `k`.

This incremental approach has a real consequence for code quality: the parser does **not** perform classical optimizations like constant folding or peephole rewriting. Those would require a separate AST pass. Instead, the VM relies on its runtime arithmetic operations and on small, explicit compiler hooks (`codebinexpval`, `codecond`, etc.) to emit idiomatic patterns. The result is bytecode that is dense, predictable, and easy to debug — exactly what you want in an embedded interpreter.

## What Bytecode Actually Looks Like

Every compiled Lua function is wrapped in a `Proto` struct (defined in `lobject.h`). The interesting fields are:

```c
typedef struct Proto {
  CommonHeader;
  lu_byte numparams;        /* number of fixed parameters */
  lu_byte is_vararg;        /* 2: vararg, 0: regular */
  lu_byte maxstacksize;     /* number of registers needed */
  int sizeupvalues;         /* size of 'upvalues' */
  int sizek;                /* size of 'k' (constants) */
  int sizelineinfo;
  int sizecode;             /* number of instructions */
  Instruction *code;        /* bytecode instructions */
  TValue *k;                /* constants */
  struct Proto **p;         /* nested functions */
  ...
} Proto;
```

Each instruction is a 32-bit unsigned integer with this layout, defined in `lopcodes.h`:

```text
   31       24 23      16 15      8 7        0
   +----------+----------+----------+----------+
   |   B/C    |    k     |    A     |  opcode  |
   +----------+----------+----------+----------+
```

- **opcode** (8 bits): the operation.
- **A** (8 bits): the primary register or constant slot.
- **B/C** (16 bits, used as B or C depending on the instruction): secondary operand.
- **k** (1 bit): a boolean flag for instructions like `OP_ADD`, where it selects "constant on the right."

Constants live in the `k` array; nested closures live in `p`; upvalues are tracked separately because they refer to variables from enclosing function scopes rather than to constants.

You can see this representation directly by running `luac -l` against any source file:

```bash
$ echo 'local x = 1; print(x + 2)' > sample.lua
$ luac -l sample.lua
```

The output shows each instruction, its operands, and the active line number. For our one-line program, you get a sequence like:

```text
main <sample.lua:1,1> (5 instructions, 32 bytes at 0x...)
      0+ params, 2 slots, 0 upvalues, 1 local, 1 constant, 0 functions
        1   [1]    VARARG     0   0
        2   [1]    LOADNIL    0   1
        3   [1]    SETTABUP   0 0 -1   ; 0, "x", 1
        4   [1]    GETTABUP   1 0 -1   ; 0, "x"
        5   [1]    ADD        1   0 -2   ; inlined 2
        6   [1]    GETTABUP   2 0 -3   ; 0, "print"
        7   [1]    CALL       2   1   1
        8   [1]    RETURN     0   1
      constants (1) for 0x...:
        1   1
```

Notice the constants table: the literal `2` was folded into the `ADD` instruction's `B` slot, but the literal `1` for `x` was kept as a constant because it is referenced via a table (`SETTABUP`). The `k` (inlined constant) bit is what makes this trick possible.

## Patterns in Production: The Register Model

The single biggest difference between the Lua VM and a stack-based interpreter like CPython or the JVM is that Lua instructions **operate on registers**. Each running function owns a contiguous slice of the Lua stack — the "call frame" — and the compiler assigns expressions to specific slots in that frame.

This has practical consequences:

- **Temporaries are free.** No `PUSH` and `POP` instructions to shuffle values around. The `ADD a b c` form lets the compiler pick where the result lives.
- **Instruction count is low.** Adding two numbers and storing the result is one instruction, not three.
- **The interpreter loop is simple.** The dispatch switch needs far fewer cases — Lua 5.4 has about 85 opcodes, compared to over 200 in some stack VMs.

The downside is that registers are a per-call-frame resource, so a function call must reallocate a frame and assign new register slots. Lua handles this through `luaD_precall` in `ldo.c`, which grows the stack if needed and computes the new base pointer.

A typical call frame looks like:

```text
function slots:  [func][arg1][arg2][...][return1][return2]
                   ^
                 base pointer (ci->func + 1)
```

The interpreter always knows where the current frame starts, so any instruction can refer to "register 0" (the function being called), register 1 (the first argument), or register 2 (the second argument) without indirection.

## The Dispatch Loop

At the heart of `lvm.c` is `luaV_execute`, the interpreter function. It looks roughly like this:

```c
int luaV_execute(lua_State *L) {
  CallInfo *ci = L->ci;
  L->stack_last = L->top + LUA_MAXSTACK;
  for (;;) {
    Instruction i = *(ci->u.l.savedpc++);
    StkId ra = RA(i);   /* register A */
    OpCode op = GET_OPCODE(i);
    switch (op) {
      case OP_MOVE: {
        setobjs2s(L, ra, RB(i));
        vmbreak;
      }
      case OP_LOADK: {
        TValue *rb = KBx(i);
        setobj2s(L, ra, rb);
        vmbreak;
      }
      case OP_RETURN: {
        int n = GETARG_B(i) - 1;
        ...
      }
      /* ~85 cases total */
    }
  }
}
```

The loop is intentionally tiny. Each iteration:

1. Fetches the next instruction from the saved program counter.
2. Computes the address of register `A`.
3. Switches on the opcode.
4. `vmbreak` jumps back to the top of the `for (;;)`.

This is a textbook portable interpreter. There is no threaded code, no computed gotos (in the default build, although you can enable `LUA_USE_COMPUTED_GOTO` for a 10–20% speedup), no hidden state machine. The interpreter reads like the bytecode specification it implements.

A subtle but important detail: **the saved program counter is stored in the `CallInfo`, not in a global**. This is what makes coroutines cheap — a coroutine simply swaps its `CallInfo`, and the same `luaV_execute` loop keeps running. We'll see how that interacts with closures and upvalues next.

## Closures, Upvalues, and the Closure Problem

Closures in Lua are values, not a special feature bolted on. When the compiler encounters an anonymous function that captures a local variable, it:

1. Emits the inner function's `Proto`.
2. Marks the captured local as an "upvalue" in the outer function.
3. At runtime, calls `OP_CLOSURE`, which tells the VM to instantiate a closure from the prototype and resolve each upvalue against either an enclosing local (an "open" upvalue) or an already-closed upvalue from an enclosing function.

The trick is that an upvalue may outlive the function that captured it. The VM handles this with a linked list of "open upvalues" anchored at each stack position. When a stack slot is reused, its open upvalues are "closed" — their value is moved into a heap-allocated `UpVal` struct, and future accesses go through a pointer.

This is one of the most elegant pieces of the VM. The chain is maintained in `lvm.c` by `luaF_findupval` and friends. If you want to read the canonical explanation, [the Lua Reference Manual's section on visibility rules](https://www.lua.org/manual/5.4/manual.html) describes the semantic side, while `lfunc.c` and `luac.c` show the data structures.

## Garbage Collection: Generational, Incremental, Concurrent-ish

Lua 5.4 introduced a generational mode for the GC. Earlier versions used a single incremental mark-and-sweep collector. The 5.4 collector still supports the old mode, but the default (`LUA_GCGEN`) splits the heap into a young generation (collected frequently, cheaply) and an old generation (collected rarely, with full mark-and-sweep). The collector is incremental: it does a small chunk of work per allocation, bounded by the GC pause parameter.

From a working engineer's perspective, the things to know are:

- The collector is **non-moving**. It does not compact the heap, which keeps pointers stable — a useful property when Lua values are embedded in C structures.
- The collector is **conservative with respect to the C stack** — it scans the C stack for values that look like Lua tagged pointers and treats them as roots.
- The collector is **cooperative with the VM**. The dispatch loop calls `luaC_condGC` at key points (function calls, loop back-edges) so the collector can interleave work without preempting the interpreter.
- You can call `collectgarbage("count")`, `"collect"`, `"step"`, `"stop"`, `"restart"`, and a handful of other commands from script code, giving you fine-grained control — handy in long-running services like OpenResty.

If you want to see the generational implementation, read `lgc.c` from `gcstate` onward. The transitions between `GCSpropagate`, `GCSatomic`, and `GCSswpallgc` are the major phases of a full collection cycle.

## Coroutines: VM Multitasking

Lua's coroutines are symmetric in the sense that any function can `yield` and be resumed, but asymmetric in the sense that the yield/resume protocol is explicit. The implementation leans on the fact that each Lua state has only one call stack, with `CallInfo` linked through `ci->previous` and `ci->next`. To yield:

1. The `OP_RETURN`-style yield path in `lvm.c` calls `luaD_throw` with a special exception tag.
2. The exception unwinds back to the top-level resume driver (`luaB_yield` or `lua_resume`), which saves the current `ci`.
3. On resume, the saved `ci` is restored and `luaV_execute` is called again, picking up exactly where it left off.

Because the program counter lives in the `CallInfo`, the same interpreter loop can suspend and resume any number of coroutines, each with its own stack of frames. This is also why Lua's coroutines cannot call across C frames in arbitrary ways — only frames that the VM knows about can be saved and restored cleanly.

For a working engineer building a pipeline scheduler, this model is attractive. Tools like [Cloudflare's OpenResty](https://openresty.org/) use Lua coroutines for non-blocking I/O, and the pattern is essentially "yield until socket is ready, then resume."

## Strings, Tables, and the Tagged Value Trick

One reason Lua's interpreter is so small is the **tagged-value** representation of all values. A `TValue` is a small struct holding a `Value` union and a `tt` type tag:

```c
typedef union Value {
  GCObject *gc;    /* collectible objects */
  void *p;         /* light userdata */
  int b;           /* booleans */
  lua_CFunction f; /* C functions */
  lua_Integer i;   /* integers */
  lua_Number n;    /* floats */
} Value;

typedef struct TValue {
  union Value value_;
  int tt_;
} TValue;
```

A single 16-byte value can hold a string, table, integer, float, or pointer, with the type tag telling the interpreter which union member to use. There is no boxing overhead for primitives, no per-type dispatch, and no separate small-integer cache. The cost is that you cannot store raw C pointers as Lua values without going through `lightuserdata`, and you cannot store raw integers larger than the `lua_Integer` range (typically 64 bits).

Tables are the workhorse data structure. They start as arrays and grow into hash-backed maps as non-integer keys appear. The implementation in `ltable.c` uses an open-addressed hash table with a twist: integer keys are stored in a separate array segment when possible, so `t[1]`, `t[2]`, `t[3]` use no hash computation at all. This is why Lua tables are so competitive with arrays in dynamic languages.

## Why the Design Has Held Up

Three properties explain why the reference Lua VM has stayed at the center of so many ecosystems for over two decades:

1. **Predictability.** The bytecode format is stable, the call frame model is uniform, and the GC is conservative and non-moving. Embedding it into a host application does not require heroic effort.
2. **Footprint.** A full Lua interpreter can compile to under 200 KB of machine code with stripped symbols, and the runtime allocator is pluggable. This is why it runs on everything from microcontrollers to cloud servers.
3. **Performance density.** Because the VM is register-based, and because the parser emits code incrementally without sacrificing too much optimization, the gap between Lua and JIT-tier interpreters narrows for many workloads. LuaJIT extends this further, but the reference VM already competes well per kilobyte of code.

The price for all of this is that there is no JIT in the reference distribution, no native threading, no SIMD-aware numerics, and no FFI to call C directly without going through the C API. For many embedded use cases, none of those matter. For others, LuaJIT — or languages built on top of the same ideas, like Wren, Luau, and MoonScript successors — pick up the slack.

## Key Takeaways

- The reference Lua VM is a **single-pass compiler**: the parser and code generator are interleaved in `lparser.c` and `lcode.c`, which keeps memory low and compilation fast.
- Bytecode is **register-based**, with 32-bit instructions packing an opcode, three operand fields, and a flag bit. This produces short, dense programs that are easy to dispatch.
- The interpreter is a **portable `switch`-based dispatch loop** in `lvm.c`. There is no hidden state; reading the source is reading the VM spec.
- Closures are first-class values, with upvalues handled by an **open-upvalue list** anchored at stack slots. This is one of the cleanest closure implementations in any production language.
- The 5.4 **generational GC** runs incrementally between bytecode instructions, giving responsive pause behavior in long-running services.
- Coroutines work because the **program counter lives in the `CallInfo`**, so yielding is just saving and restoring that struct.
- The **tagged-value representation** (`TValue`) is the central trick that keeps the VM small, with a single 16-byte struct holding strings, tables, integers, floats, pointers, and C functions.

## Further Reading

- [The Lua 5.4 Reference Manual](https://www.lua.org/manual/5.4/manual.html) — the authoritative spec, including bytecode semantics.
- [The Lua 5.4 Source Code Index](https://www.lua.org/source/5.4/) — browsable hyperlinked C source, perfect for reading along with this post.
- [Roberto Ierusalimschy, "The Implementation of Lua 5.0"](https://www.lua.org/doc/tecsof-5.0.html) — the original paper on the register-based VM design.
- [Roberto Ierusalimschy, Luiz Henrique de Figueiredo, Waldemar Celes, "The Evolution of Lua" (HOPL IV)](https://www.lua.org/doc/hopl.pdf) — a tour through Lua's design history, including the move to integer/float subtypes and the generational GC.
- [Cloudflare's OpenResty project](https://openresty.org/) — a real-world production system that embeds the reference Lua VM for non-blocking I/O at scale.
- [LuaJIT](https://luajit.org/) — the JIT-compiled cousin of the reference VM, useful as a comparison point for what a tracing JIT adds on top of the register-based model.