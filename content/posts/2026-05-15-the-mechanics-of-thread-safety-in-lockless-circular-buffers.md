---
title: "The Mechanics of Thread Safety in Lockless Circular Buffers"
date: "2026-05-15T21:01:04.290"
draft: false
tags: ["concurrency", "circular-buffer", "lock-free", "thread-safety", "systems-programming"]
description: "Explore how lockless circular buffers achieve thread safety using atomic operations, memory ordering, and cache-friendly designs, with practical C examples."
summary: "A deep dive into lockless circular buffer design, showing how atomic primitives, memory fences, and careful indexing keep multiple producers and consumers safe without locks."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-15-the-mechanics-of-thread-safety-in-lockless-circular-buffers.svg"
  alt: "Illustration of a circular buffer with atomic pointers."
  caption: ""
  relative: false
---

> **TL;DR** — Lockless circular buffers achieve thread safety by using atomic read‑modify‑write primitives, proper memory ordering, and a single‑writer/single‑reader or multi‑producer/multi‑consumer protocol that avoids data races without mutexes.

Circular buffers (also called ring buffers) are a staple in low‑latency systems: networking stacks, audio pipelines, and inter‑thread communication channels all rely on them. The “lockless” qualifier often scares newcomers because it sounds like magic, but the safety guarantees come from a disciplined use of atomic operations and memory ordering rules defined by the C11/C++11 memory model. This article walks through the geometry of a ring, the atomic primitives that make it safe, concrete SPSC and MPMC implementations in C, and the performance tricks that keep the design cache‑friendly.

## Foundations of Circular Buffers

A circular buffer stores a fixed number of elements in a contiguous memory region. Two indices—*head* (read position) and *tail* (write position)—move forward modulo the capacity. When the *tail* catches up to the *head*, the buffer is full; when the *head* catches up to the *tail*, it is empty.

### Buffer geometry and indexing

```
+---------------------------+   capacity = N
| 0 | 1 | 2 | … | N‑2 | N‑1 |
+---------------------------+
   ^               ^
   |               |
 head (read)      tail (write)
```

Because the indices wrap around, the effective position is `index % N`. This modulo operation can be optimized with power‑of‑two capacities, allowing a bitmask (`index & (N‑1)`) instead of a division.

Two invariants must hold at all times:

1. **No overwrite:** `tail - head <= N` (the distance never exceeds capacity).
2. **No under‑read:** `head <= tail` (the read pointer never passes the write pointer).

In a single‑threaded world these are trivial; in a concurrent setting we must guarantee that *all* threads observe a consistent view of `head` and `tail`.

## Atomic Operations and Memory Ordering

C11 introduced a portable set of atomic types (`_Atomic`) and operations (`atomic_load`, `atomic_store`, `atomic_fetch_add`, `atomic_compare_exchange_weak`, …). These are the building blocks of a lockless buffer.

### Compare‑and‑Swap (CAS) vs Fetch‑Add

* **CAS** (`atomic_compare_exchange_*`) atomically swaps a value only if it matches an expected old value. It is the classic primitive for implementing lock‑free queues because it can detect contention without blocking.
* **Fetch‑Add** (`atomic_fetch_add`) adds a delta and returns the previous value. It is useful when a thread can claim a slot by incrementing a counter, as in many MPMC designs.

Both operations accept a *memory order* argument (`memory_order_relaxed`, `memory_order_acquire`, `memory_order_release`, `memory_order_acq_rel`, `memory_order_seq_cst`). Choosing the right order is what gives us thread safety without a lock.

### Memory fences and acquire/release semantics

* **Release** (`memory_order_release`) on a store guarantees that all prior writes in the same thread become visible *before* the store becomes visible to other threads.
* **Acquire** (`memory_order_acquire`) on a load guarantees that all subsequent reads see the effects of writes that happened-before the corresponding release store.
* **Seq‑cst** (`memory_order_seq_cst`) imposes a total order on all sequentially consistent operations, simplifying reasoning at the cost of performance.

A typical producer‑consumer pair uses a *release* on the write pointer and an *acquire* on the read pointer:

```c
/* Producer */
size_t pos = atomic_fetch_add_explicit(&buf->tail, 1, memory_order_acquire);
buf->data[pos & mask] = item;                // write payload
atomic_store_explicit(&buf->slot[pos & mask].ready, true, memory_order_release);

/* Consumer */
while (!atomic_load_explicit(&buf->slot[head & mask].ready,
                             memory_order_acquire)) {
    /* spin‑wait */
}
item = buf->data[head & mask];
atomic_store_explicit(&buf->slot[head & mask].ready, false,
                      memory_order_relaxed);
head = (head + 1) & mask;
```

The release on `ready` ensures the payload write is visible before the consumer sees `ready == true`. The acquire on the consumer side guarantees the payload is fully visible after it observes `ready`.

## Single‑Producer / Single‑Consumer (SPSC) Implementation

When there is exactly one producer and one consumer, the design can be dramatically simpler because each side exclusively updates one index. No CAS is needed; a plain atomic store/load with appropriate ordering suffices.

### Code example (C)

```c
/* spsc_ring.h */
#ifndef SPSC_RING_H
#define SPSC_RING_H

#include <stdatomic.h>
#include <stddef.h>
#include <stdbool.h>

typedef struct {
    size_t capacity;          // must be power of two
    size_t mask;              // capacity - 1
    _Atomic size_t head;      // read index – consumer only writes
    _Atomic size_t tail;      // write index – producer only writes
    void **buffer;            // array of void* (generic payload)
} spsc_ring_t;

/* Initialise a ring; caller provides pre‑allocated buffer */
static inline void spsc_ring_init(spsc_ring_t *r, void **buf,
                                   size_t capacity)
{
    r->capacity = capacity;
    r->mask = capacity - 1;
    r->head = ATOMIC_VAR_INIT(0);
    r->tail = ATOMIC_VAR_INIT(0);
    r->buffer = buf;
}

/* Push returns false if the ring is full */
static inline bool spsc_ring_push(spsc_ring_t *r, void *item)
{
    size_t tail = atomic_load_explicit(&r->tail, memory_order_relaxed);
    size_t next = tail + 1;
    size_t head = atomic_load_explicit(&r->head, memory_order_acquire);
    if (next - head > r->capacity)           // full
        return false;

    r->buffer[tail & r->mask] = item;
    atomic_store_explicit(&r->tail, next, memory_order_release);
    return true;
}

/* Pop returns NULL if the ring is empty */
static inline void *spsc_ring_pop(spsc_ring_t *r)
{
    size_t head = atomic_load_explicit(&r->head, memory_order_relaxed);
    size_t tail = atomic_load_explicit(&r->tail, memory_order_acquire);
    if (head == tail)                        // empty
        return NULL;

    void *item = r->buffer[head & r->mask];
    atomic_store_explicit(&r->head, head + 1, memory_order_release);
    return item;
}
#endif /* SPSC_RING_H */
```

**Explanation of ordering choices**

* The producer reads `head` with *acquire* to see the most recent consumer progress. This prevents it from overwriting a slot that the consumer has not yet reclaimed.
* The producer stores the new `tail` with *release* after writing the payload, guaranteeing the payload is visible before the consumer can see the updated `tail`.
* The consumer mirrors the pattern: it reads `tail` with *acquire* to confirm there is data, and stores the new `head` with *release* after consuming the payload.

Because each index is touched by only one thread, there is no risk of data races on the indices themselves, and the only shared data that needs ordering are the payload slots.

## Multi‑Producer / Multi‑Consumer (MPMC) Strategies

When multiple producers or consumers exist, we must protect the shared indices from concurrent updates. Two common approaches are:

1. **Sequence‑counter rings** (a.k.a. “bounded MPMC queue”).
2. **Per‑slot flags with CAS** to claim ownership.

Both rely on atomic compare‑exchange to serialize slot acquisition.

### Ring buffer with sequence counters

A classic algorithm, described by Dmitry Vyukov, uses a per‑slot *sequence* number that indicates whether a slot is ready to be written or read. The sequence starts at the slot index and increments by the capacity each cycle.

```c
/* vyukov_mpmc.h – simplified version */
#ifndef VYUKOV_MPMC_H
#define VYUKOV_MPMC_H

#include <stdatomic.h>
#include <stddef.h>
#include <stdbool.h>

typedef struct {
    _Atomic size_t seq;   // monotonically increasing sequence
    void *data;
} vslot_t;

typedef struct {
    size_t capacity;       // power of two
    size_t mask;
    vslot_t *slots;        // array of slots
    _Atomic size_t head;   // consumer index
    _Atomic size_t tail;   // producer index
} vmpmc_ring_t;

/* Initialise */
static inline void vmpmc_init(vmpmc_ring_t *r, vslot_t *buf, size_t capacity)
{
    r->capacity = capacity;
    r->mask = capacity - 1;
    r->head = ATOMIC_VAR_INIT(0);
    r->tail = ATOMIC_VAR_INIT(0);
    for (size_t i = 0; i < capacity; ++i) {
        atomic_store_explicit(&buf[i].seq, i, memory_order_relaxed);
    }
    r->slots = buf;
}

/* Enqueue – returns false if queue is full */
static inline bool vmpmc_enqueue(vmpmc_ring_t *r, void *item)
{
    vslot_t *slot;
    size_t pos, seq, dif;

    while (1) {
        pos = atomic_load_explicit(&r->tail, memory_order_relaxed);
        slot = &r->slots[pos & r->mask];
        seq = atomic_load_explicit(&slot->seq, memory_order_acquire);
        dif = (intptr_t)seq - (intptr_t)pos;

        if (dif == 0) {
            /* slot is free; try to claim it */
            if (atomic_compare_exchange_weak_explicit(
                    &r->tail, &pos, pos + 1,
                    memory_order_relaxed, memory_order_relaxed))
                break;          // claimed successfully
        } else if (dif < 0) {
            return false;       // queue full
        } else {
            /* another producer moved tail forward; retry */
        }
    }

    slot->data = item;
    atomic_store_explicit(&slot->seq, pos + 1, memory_order_release);
    return true;
}

/* Dequeue – returns NULL if empty */
static inline void *vmpmc_dequeue(vmpmc_ring_t *r)
{
    vslot_t *slot;
    size_t pos, seq, dif;

    while (1) {
        pos = atomic_load_explicit(&r->head, memory_order_relaxed);
        slot = &r->slots[pos & r->mask];
        seq = atomic_load_explicit(&slot->seq, memory_order_acquire);
        dif = (intptr_t)seq - (intptr_t)(pos + 1);

        if (dif == 0) {
            if (atomic_compare_exchange_weak_explicit(
                    &r->head, &pos, pos + 1,
                    memory_order_relaxed, memory_order_relaxed))
                break;          // claimed successfully
        } else if (dif < 0) {
            return NULL;        // queue empty
        } else {
            /* another consumer moved head forward; retry */
        }
    }

    void *item = slot->data;
    atomic_store_explicit(&slot->seq,
                           pos + r->capacity,
                           memory_order_release);
    return item;
}
#endif /* VYUKOV_MPMC_H */
```

**Why the sequence works**

* When a producer sees `seq == pos`, the slot is empty and can be claimed. After storing the payload, it increments `seq` to `pos + 1`, signalling “ready”.
* A consumer expects `seq == pos + 1`. Upon reading, it resets the sequence to `pos + capacity`, which corresponds to the next cycle’s empty state.
* Because `seq` is always monotonic, wrap‑around is handled naturally as long as `size_t` does not overflow (practically impossible).

The algorithm uses only *relaxed* loads for the index variables (`head`, `tail`) because the crucial ordering is enforced by the per‑slot sequence’s acquire/release pair.

### Hazard pointers and the ABA problem

When using CAS on a pointer that can be reclaimed, the classic ABA problem may arise: a slot can be freed, reused, and appear unchanged to a CAS operation, leading to a false positive. In lockless queues, the sequence counter technique sidesteps ABA because the counter always changes, even if the slot content cycles.

If you need to store actual heap‑allocated objects, consider **hazard pointers** or **epoch‑based reclamation** (see the Linux kernel’s RCU). These mechanisms let a thread announce that it holds a reference, preventing another thread from freeing the object until all hazard pointers are cleared.

## Performance Considerations

Thread safety is only useful if the structure remains fast under contention. The following tactics keep the lockless buffer cache‑friendly.

### Cache line alignment

False sharing occurs when two atomic variables that are updated by different cores reside on the same cache line (typically 64 bytes). A write to one variable forces the whole line to bounce between cores, throttling throughput.

* Align `head` and `tail` on separate cache lines (`alignas(64)` in C11).
* Pad the `vslot_t` structure so that `seq` and `data` do not share a line with neighboring slots.

```c
typedef struct {
    _Atomic size_t seq;
    void *data;
    char _pad[64 - sizeof(_Atomic size_t) - sizeof(void*)]; // ensure 64‑byte slot
} vslot_t;
```

### False sharing avoidance in multi‑producer scenarios

Even with per‑slot sequencing, the `tail` index can become a hotspot. One technique is **distributed enqueue counters**: each producer grabs a chunk of indices with a single atomic fetch‑add, then works on its private range without further atomic updates until the chunk is exhausted.

```c
size_t chunk = atomic_fetch_add_explicit(&r->tail, BATCH_SIZE,
                                         memory_order_relaxed);
for (size_t i = 0; i < BATCH_SIZE; ++i) {
    size_t pos = chunk + i;
    // write into slot[pos & mask] without further atomics
}
```

The trade‑off is increased latency for the last element of each batch, but overall throughput improves under high contention.

## Key Takeaways

- Lockless circular buffers rely on **C11 atomic primitives** and **memory‑order semantics** (acquire/release) to guarantee that producers and consumers see a consistent view of the data without mutexes.  
- **Single‑producer/single‑consumer (SPSC)** designs can use simple atomic loads/stores because each index is owned by a single thread.  
- **Multi‑producer/multi‑consumer (MPMC)** buffers need **compare‑exchange** or **fetch‑add** together with a per‑slot **sequence counter** to avoid the ABA problem and to coordinate ownership.  
- **Cache‑friendly layout** (power‑of‑two capacity, cache‑line alignment, padding) eliminates false sharing and preserves the low‑latency advantage of lock‑free designs.  
- When buffers store heap‑allocated objects, incorporate **hazard pointers** or an **epoch‑based reclamation** scheme to prevent use‑after‑free bugs.

## Further Reading

- [Lock‑Free Programming](https://en.wikipedia.org/wiki/Lock-free_programming) – overview of lock‑free concepts and common pitfalls.  
- [Bounded MPMC Queue (Vyukov)](https://www.1024cores.net/home/lock-free-algorithms/queues/bounded-mpmc-queue) – original description of the sequence‑counter algorithm.  
- [C11 atomic operations](https://en.cppreference.com/w/c/atomic) – comprehensive reference for atomic types, functions, and memory orders.  
- [Boost.Lockfree documentation](https://www.boost.org/doc/libs/release/libs/lockfree/doc/html/index.html) – ready‑made lock‑free containers for C++.  
- [Linux kernel ring buffer design](https://www.kernel.org/doc/html/latest/ring_buffer.html) – practical usage of ring buffers inside the kernel.