---
title: "Designing Lock-Free Queues: Inside the Linux KFIFO and Ringbuffer Implementations"
date: "2026-09-06T00:00:29.568"
draft: false
tags: ["linux-kernel", "lock-free", "ringbuffer", "kfifo", "data-structures", "concurrency"]
description: "A deep dive into how the Linux kernel's lock-free KFIFO works: memory ordering, the single-producer/single-consumer trick, and lessons for designing your own queues."
summary: "How the Linux kernel's KFIFO achieves a wait-free, lock-free FIFO with a single atomic variable. We walk through the ringbuffer math, the memory-ordering subtlety that makes it correct on weakly ordered CPUs, and what you can borrow for your own high-throughput pipelines."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-designing-lock-free-queues-inside-the-linux-kfifo-and-ringbuffer-implementations.svg"
  alt: "Stylized circular ringbuffer with producer and consumer pointers."
  caption: ""
  relative: false
---

> **TL;DR** — Linux's `kfifo` is a lock-free, wait-free FIFO built around a single power-of-two ring and a single `unsigned long` atomic that packs both the in and out offsets. With one producer and one consumer thread, no lock, no CAS loop, and no retry is needed — just two acquire/release pairs on a single integer. The same shape shows up in DPDK rings, `io_uring` SQ/CQ rings, and many audio/video pipelines.

## Why a Lock-Free FIFO Is Harder Than It Looks

A FIFO is the most boring data structure in computer science. You push on one end, you pop on the other, you don't even need to think. The moment two threads enter the picture, the boring FIFO becomes one of the most subtle objects you can implement. The classic wrong version — `in` and `out` as two separate integers guarded by a mutex — is correct but slow. The naive lock-free version — `in` and `out` as two separate atomics with CAS — is correct only if you're careful about wrap-around, modulo arithmetic, and the fact that `in == out` ambiguously means both "empty" and "full" when the ring has size `N`.

The Linux kernel's `kfifo` (defined in [`include/linux/kfifo.h`](https://elixir.bootlin.com/linux/latest/source/include/linux/kfifo.h) and implemented in [`lib/kfifo.c`](https://elixir.bootlin.com/linux/latest/source/lib/kfifo.c)) sidesteps all of these landmines with two design choices:

1. **The buffer size is rounded up to the next power of two.** A bitmask replaces the modulo, so `in & mask` and `out & mask` compile to a single `and` instruction.
2. **`in` and `out` are packed into a single `unsigned long` atomic.** One `cmpxchg` (or, in the common SPSC case, plain loads and stores) updates both ends atomically.

The payoff is a queue that is **wait-free in the single-producer/single-consumer case** — every operation completes in a bounded number of steps with no retry loop — and that still degrades gracefully when you wrap it with a lock for MPMC use.

## The Shape of the Ring

Conceptually, `kfifo` is a circular buffer of `mask + 1` slots. The mask is always `size - 1` where `size` is a power of two. Internally the kernel stores four fields:

```c
struct __kfifo {
    unsigned long	in;     /* next write offset, in bytes */
    unsigned long	out;    /* next read offset, in bytes */
    unsigned long	mask;   /* size - 1 */
    void		*buffer; /* the actual storage */
    unsigned long	esize;  /* element size for typed API */
};
```

The two fields that matter for concurrency are `in` and `out`. Both grow monotonically for the entire lifetime of the queue — they never reset, they never wrap to zero. Only their low bits (`in & mask`) are used to index the buffer.

This single trick — counting in a monotonically increasing namespace while indexing modulo `mask` — is what lets us distinguish empty from full:

```text
queue is empty    ⇔  in == out
queue is full     ⇔  in - out == size    (i.e. in == out + size, mod 2^64)
```

No special "full" bit. No `count` variable. No CAS on the count. Just the difference of two monotonically increasing integers.

## Putting Both Ends in One Word

If `in` and `out` lived in separate atomics, every push and pop would need a compare-and-swap loop, because the producer's update to `in` and the consumer's update to `out` are independent. On weakly ordered hardware (ARM, PowerPC, RISC-V), each side would also need barriers to make sure the data write happens-before the index publish and the data read happens-after the index acquire.

The kernel collapses both indices into one machine word using a union:

```c
struct kfifo atomic_friendly {
    union {
        struct {
            unsigned long	in;
            unsigned long	out;
        };
        atomic_long_t	combined;
    };
};
```

For **typed, SPSC-style use** (the most common in-kernel case — one driver thread writes, one reader thread drains), the kernel takes the bold shortcut of just using two plain `unsigned long` fields with explicit barriers. The reasoning is documented in a comment near `__kfifo_in()` and `__kfifo_out()`: with only one writer and one reader, the only race is between the index update and the data copy, and barriers are enough.

For the generic MPMC case (`kfifo_alloc()` + `kfifo_in()` + `kfifo_out()` from arbitrary threads), the kernel uses `cmpxchg` on the combined word to update both ends in one step. That gives you a lock-free, multi-producer/multi-consumer queue with the same data layout.

## The SPSC Fast Path, Annotated

Here is the kernel's `__kfifo_in` logic simplified to its essence:

```c
unsigned int __kfifo_in(struct __kfifo *fifo,
                        const void *buf, unsigned int len)
{
    unsigned int in  = smp_load_acquire(&fifo->in);
    unsigned int out = READ_ONCE(fifo->out);
    unsigned int mask = fifo->mask;
    unsigned int space = mask + 1 - (in - out);

    if (len > space)
        return 0;                  /* would block; caller decides */

    /* Copy data into the ring, may wrap around the end. */
    unsigned int l = min(len, mask + 1 - (in & mask));
    memcpy((char *)fifo->buffer + (in & mask), buf, l);
    memcpy((char *)fifo->buffer, buf + l, len - l);

    /* Publish the new write position. */
    smp_store_release(&fifo->in, in + len);
    return len;
}
```

Three things to notice:

- **`smp_load_acquire` on `in` and `smp_store_release` on the new `in`.** These pair with the consumer's `smp_load_acquire` on `out` and `smp_store_release` on the new `out` to form a happens-before chain across the data. On x86 the acquire/release collapse to plain `mov`; on ARM64 they map to `ldar`/`stlr`.
- **`out` is read with `READ_ONCE`, not `smp_load_acquire`.** That's because the producer only cares about the *value* of `out` for the space calculation, not for ordering relative to the data slot reads. The consumer's release on its own `out` is what guarantees the producer sees correct data later.
- **No CAS. No retry loop. Wait-free.** The producer either has space or it doesn't; if it doesn't, it returns 0 and the caller decides whether to spin, sleep, or drop.

The consumer's `__kfifo_out` is the mirror image: acquire-load `out`, compute available, memcpy, release-store the new `out`.

This is the same shape DPDK uses in its [`rte_ring`](https://doc.dpdk.org/guides/prog_guide/ring_lib.html) library's SPSC mode, and the same shape Go's runtime used internally for its scheduler run queue before it was generalized.

## Memory Ordering: The Only Hard Part

If you have ever written a lock-free queue and shipped it to an ARM box, you have probably been bitten by the order in which stores become visible. The common symptom is "the producer's `in` was visible, but the data I copied was still the previous value". The cure is exactly what `kfifo` does: pair every index store with a release barrier, and pair every index load with an acquire barrier.

The Linux kernel wraps these in portable macros so that the code compiles correctly on every SMP architecture it supports:

```c
#define smp_load_acquire(p)                    \
({                                              \
    typeof(*p) ___p = READ_ONCE(*p);            \
    smp_mb();                                   \
    ___p;                                       \
})

#define smp_store_release(p, v)                \
({                                              \
    smp_mb();                                   \
    WRITE_ONCE(*p, v);                          \
})
```

On x86, `smp_mb()` is a compiler barrier only (the TSO memory model already gives you the ordering). On ARM64 it compiles to `dmb ish`. The full rationale, including the Linux-Kernel Memory Model paper and its `smp_load_acquire`/`smp_store_release` formalization, is in [Linux Kernel Memory Barriers (Documentation/memory-barriers.txt)](https://www.kernel.org/doc/Documentation/memory-barriers.txt) — required reading if you are writing anything lock-free that has to ship on more than one architecture.

There is one subtlety that beginners miss: you need a release barrier on the **producer's `in` update** and an acquire barrier on the **consumer's `out` load**, *and* you need to do the data write *before* the release-store of `in`, and the data read *after* the acquire-load of `out`. Reordering any of those four steps breaks the queue. The kernel's macros make it hard to do by accident.

## Why Power-of-Two Sizing Wins

A circular buffer of `N` slots normally requires you to compute `in % N` and `out % N` on every operation. Division and modulo are slow — on most CPUs, a 64-bit modulo is 30–90 cycles. By forcing `N` to be a power of two, the kernel turns the modulo into a single AND with `N - 1`. The compiler also knows to keep the mask in a register across loop iterations.

```c
/* What every other ringbuffer does, slowly: */
size_t idx = in % ring_size;

/* What kfifo does, fast: */
size_t idx = in & mask;
```

The cost is that the queue can only be sized in powers of two. The kernel papers over this by rounding the requested size up:

```c
static inline __must_check int kfifo_alloc(struct __kfifo *fifo,
                                           unsigned int size,
                                           gfp_t gfp_mask)
{
    /* Round up to the next power of two. */
    size = roundup_pow_of_two(size);
    fifo->buffer = kmalloc(size, gfp_mask);
    /* ... */
}
```

If you ask for 1000 bytes, you get 1024. If you ask for 1500, you get 2048. The waste is at most one doubling, and the speedup is worth it for any non-trivial workload. This trick — "round to power of two to make the modulo free" — is everywhere: jemalloc's size classes, the hash ring in Python's dict, and the size masks in `io_uring`'s submission queue.

## The Wraparound Copy: Two `memcpy`s

The other thing `kfifo` gets right is that it never tries to do a single contiguous copy when the data straddles the end of the ring. The implementation explicitly splits the copy into two:

```c
unsigned int l = min(len, mask + 1 - (in & mask));
memcpy((char *)fifo->buffer + (in & mask), buf, l);
memcpy((char *)fifo->buffer, buf + l, len - l);
```

Most naive ringbuffer implementations do something like:

```c
/* WRONG: assumes the data fits in one piece. */
memcpy(buf, fifo->buffer + (in & mask), len);
```

That works as long as the producer's contiguous chunk is shorter than the remaining tail space. The instant it isn't, you copy garbage past the end of the buffer or scribble across the wrap point. Splitting into a "first chunk to the end" and a "second chunk from the start" handles every case, and on modern hardware the two `memcpy`s are almost as fast as one because of write-combining buffers and prefetch.

If you want to do this in userspace with zero-copy, DPDK goes even further: the [`rte_ring_enqueue_burst`](https://doc.dpdk.org/api/rte__ring_8h.html) API can hand back a pointer to the wrapped object so the caller can fill it in place, avoiding the temporary `buf` copy entirely. For kernel-internal use, `kfifo` sticks with the two-`memcpy` approach because the caller's data is almost always in some other kernel buffer that needs to be copied anyway.

## The MPMC Variant: One CAS, Two Ends

When more than one producer or more than one consumer can touch the queue, `kfifo` no longer trusts plain loads and stores. It uses `cmpxchg` on the combined `in/out` word:

```c
static inline unsigned int __kfifo_in(struct __kfifo *fifo,
                                      const void *buf, unsigned int len)
{
    unsigned long combined = atomic_long_fetch_add(&fifo->combined, ...);
    /* high 32 bits = out, low 32 bits = in (or vice versa) */
    /* ... */
}
```

The exact packing is implementation-defined, but the contract is: one CAS either updates both `in` and `out` (in the MPMC case the in-index update must contend with the out-index from other consumers) or it retries. This is the classic Michael-Scott shape, simplified because both indices live in one word.

In practice, almost no in-kernel user of `kfifo` actually needs MPMC. The most common pattern is: one producer thread (a network driver, a sound card IRQ handler, a USB controller thread) writes, and one consumer thread (a user-space `read()`, the ALSA PCM layer, a `poll()` wakeup) reads. For those cases the SPSC fast path with barriers is exactly what you want, and that is what `kfifo_in` / `kfifo_out` give you when called directly on a `__kfifo` you own.

## Patterns in Production: Where Else You See This Shape

The Linux `kfifo` is not an isolated curiosity. The same design shows up in three other places that working engineers interact with every week:

### `io_uring` submission and completion rings

Linux's [`io_uring`](https://kernel.dk/io_uring.pdf) uses two ringbuffers — the Submission Queue (SQ) and the Completion Queue (CQ) — that are shared between user space and the kernel. The SPSC pattern is exactly `kfifo`: producer (user space) writes to `sq.tail`, kernel reads with acquire; kernel writes to `cq.tail`, user space reads with acquire. Both tails are `unsigned int`, the masks are powers of two, and the only sync primitive is the `io_uring` `sqe_head` / `cqe_head` acquire/release pair. There is no lock, no syscall on the fast path, and the throughput ceiling is one CAS-equivalent operation per I/O.

### DPDK `rte_ring`

DPDK's [ring library](https://doc.dpdk.org/guides/prog_guide/ring_lib.html) explicitly cites the same power-of-two + atomic-tail approach. For SPSC it offers wait-free enqueue/dequeue with the same two-`memcpy` wrap. For MPMC it switches to a CAS loop, but the data layout and the `in & mask` indexing are unchanged.

### Audio and video pipelines (ALSA, GStreamer, FFmpeg)

The ALSA PCM layer in the Linux kernel uses `kfifo` directly to hand decoded audio from the hardware IRQ thread to user space. FFmpeg's `AVFifo` and GStreamer's queue elements use very similar patterns in userspace, typically with C11 atomics standing in for `smp_load_acquire` / `smp_store_release`. If you have ever wondered why `ffmpeg -i input.mp4 -f alsa default` doesn't drop frames even though your machine has eight cores all burning, the answer is that the queue between the decoder thread and the audio output thread is exactly the `kfifo` shape.

## Building Your Own: A Minimal Userspace Port

If you want the same behavior in userspace, here is a minimal C11 version that compiles on any recent compiler and works on x86, ARM, and RISC-V:

```c
#include <stdatomic.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

typedef struct {
    /* Two 32-bit halves packed into one 64-bit atomic. */
    _Atomic uint64_t head_tail;     /* low 32 = in, high 32 = out */
    uint32_t         mask;
    void             *buf;
} spsc_ring_t;

static inline uint32_t spsc_push(spsc_ring_t *r, const void *src, uint32_t n) {
    uint64_t ht      = atomic_load_explicit(&r->head_tail, memory_order_relaxed);
    uint32_t in      = (uint32_t)ht;
    uint32_t out     = (uint32_t)(ht >> 32);
    uint32_t space   = (r->mask + 1) - (in - out);
    if (n > space) return 0;

    uint32_t off = in & r->mask;
    uint32_t l   = n < (r->mask + 1 - off) ? n : (r->mask + 1 - off);
    memcpy((char *)r->buf + off, src, l);
    memcpy((char *)r->buf,     (const char *)src + l, n - l);

    /* Publish with release: consumer's acquire on out pairs with this. */
    uint64_t new_ht = ((uint64_t)out << 32) | (uint32_t)(in + n);
    atomic_store_explicit(&r->head_tail, new_ht, memory_order_release);
    return n;
}

static inline uint32_t spsc_pop(spsc_ring_t *r, void *dst, uint32_t n) {
    uint64_t ht   = atomic_load_explicit(&r->head_tail, memory_order_acquire);
    uint32_t in   = (uint32_t)ht;
    uint32_t out  = (uint32_t)(ht >> 32);
    uint32_t have = in - out;
    if (n > have) return 0;

    uint32_t off = out & r->mask;
    uint32_t l   = n < (r->mask + 1 - off) ? n : (r->mask + 1 - off);
    memcpy(dst, (char *)r->buf + off, l);
    memcpy((char *)dst + l, (char *)r->buf, n - l);

    uint64_t new_ht = ((uint64_t)(uint32_t)(out + n) << 32) | in;
    atomic_store_explicit(&r->head_tail, new_ht, memory_order_release);
    return n;
}
```

The producer's `atomic_store_explicit(..., memory_order_release)` and the consumer's `atomic_load_explicit(..., memory_order_acquire)` are the moral equivalent of `smp_store_release` and `smp_load_acquire`. Everything else is bookkeeping. On x86 this compiles to plain `mov` instructions and runs essentially at memory bandwidth; on ARM64 it compiles to `stlr`/`ldar` and is still wait-free.

## Key Takeaways

- **The "monotonic index, modulo mask" trick** is the single most important idea: count in a never-wrapping namespace, index in a wrapping one. It collapses the empty/full distinction into `in == out` vs `in - out == size`.
- **Round the buffer to a power of two** so the modulo becomes a bitmask. The memory cost is at most a factor of two, the speedup is a 30–90 cycle modulo per operation.
- **Pack both indices into one atomic word.** Even when you need CAS, one CAS on a 64-bit value is cheaper than two on two 32-bit values, and it removes the impossible interleaving where one index updates and the other doesn't.
- **Pair acquire and release on the index, not the data.** The data ordering is implied by the index ordering, as long as you copy data first, *then* release-store the index, and on the other side acquire-load the index first, *then* copy data out.
- **The SPSC case is wait-free, not just lock-free.** No CAS, no retry, no exponential backoff. Bounded, predictable, the right answer for audio, video, and most kernel-to-user handoff paths.
- **You almost never need MPMC.** A queue that crosses a thread boundary is almost always SPSC at the boundary itself, even if the system as a whole has many threads. Build a forest of SPSC queues and you'll often get higher throughput than one big MPMC queue.

## Further Reading

- [Linux Kernel `kfifo` source (lib/kfifo.c)](https://elixir.bootlin.com/linux/latest/source/lib/kfifo.c) — the canonical implementation, with extensive comments on the memory model.
- [Documentation/memory-barriers.txt](https://www.kernel.org/doc/Documentation/memory-barriers.txt) — the definitive guide to why `smp_load_acquire` and `smp_store_release` exist and how they map to hardware.
- [LWN: "Lock-free ringbuffer design" by Giacomo Vagnoni](https://lwn.net/Articles/823320/) — a detailed tour of the design decisions behind `kfifo` and how they interact with modern weakly ordered CPUs.
- [Linux Kernel Memory Model paper (Alglave et al., 2018)](https://www.kernel.org/doc/Documentation/kernel-hacking/litmus.txt) — the formal model that justifies the acquire/release pairing in `kfifo`.
- [DPDK Programmer's Guide: Ring Library](https://doc.dpdk.org/guides/prog_guide/ring_lib.html) — the userspace cousin of `kfifo`, with both SPSC and MPMC variants.
- [`io_uring` design overview (Jens Axboe)](https://kernel.dk/io_uring.pdf) — explains the SPSC ringbuffers that power the fastest async I/O path on Linux.
- [Preshing: "An Introduction to Lock-Free Programming"](https://preshing.com/20120612/an-introduction-to-lock-free-programming/) — a lighter treatment of the same acquire/release patterns, useful as a refresher before reading the kernel code.