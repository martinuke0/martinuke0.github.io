---
title: "How Sequence Locks Achieve Optimistic Reads in the Linux Kernel"
date: "2026-05-19T12:00:10.838"
draft: false
tags: ["linux", "kernel", "synchronization", "optimistic-locking", "seq-lock"]
description: "Explore how Linux sequence locks enable fast optimistic reads, their implementation details, pitfalls, and best‑practice usage in kernel code."
summary: "A deep dive into Linux's sequence lock (seqlock) mechanism, showing how it provides lock‑free reads while preserving consistency."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-19-how-sequence-locks-achieve-optimistic-reads-in-the-linux-kernel.png"
  alt: "Diagram of a sequence lock showing readers and writer."
  caption: ""
  relative: false
---

> **TL;DR** — Sequence locks (seqlocks) let writers serialize updates with a simple counter while readers perform lock‑free, optimistic reads that are validated by checking the counter before and after the read. The pattern yields very low read‑side overhead, making it ideal for high‑frequency, read‑heavy kernel data such as statistics or per‑CPU counters.

In the Linux kernel, data structures that are read far more often than they are written can become bottlenecks when protected by traditional spinlocks or mutexes. Sequence locks (often abbreviated as *seqlocks*) were introduced to address this imbalance by allowing readers to proceed without taking a lock, trusting that a quick validation step will catch any concurrent write. This article unpacks the design, the kernel APIs, real‑world usage patterns, and the trade‑offs you need to consider before reaching for a seqlock.

## The Problem: Contention in Shared Data Structures

Kernel subsystems—networking, scheduler statistics, filesystem metadata—frequently expose counters or small structs that many CPUs read each tick. When those structures are protected by a spinlock, each read incurs:

1. **Lock acquisition latency** – the CPU must wait for the writer to release the lock.
2. **Cache line bouncing** – the lock variable moves between cores, polluting caches.
3. **Potential dead‑lock scenarios** – especially when readers are preempted while holding a lock.

For a read‑heavy workload, the cost of the lock can dwarf the cost of the actual data access, inflating latency and hurting scalability on many‑core systems. An optimistic approach—*read first, verify later*—offers a way to sidestep these costs.

## Sequence Locks: Core Concepts

A sequence lock is built around a single unsigned integer called the *sequence counter*. The counter is incremented **twice** on each write: once at the start (making it odd) and once at the end (making it even). Readers capture the counter before reading the protected data and compare it after the read; if the counter changed or is odd, the read is considered invalid and must be retried.

### Data Structure of a seqlock

```c
struct seqlock {
    unsigned int seq;
};
```

The `seq` field is the only mutable state. Because the counter is never decremented, wrap‑around is harmless: a 32‑bit counter will overflow only after billions of writes, and the odd/even parity test remains valid.

### Writer Path: Updating with a Sequence Counter

The writer follows a simple two‑step protocol:

```c
void write_seqbegin(struct seqlock *sl)
{
    /* Increment to odd value – signals “write in progress”. */
    preempt_disable();               /* optional, prevents preemption */
    __sync_fetch_and_add(&sl->seq, 1);
    smp_wmb();                       /* ensure ordering of writes */
}

void write_seqend(struct seqlock *sl)
{
    smp_wmb();                       /* ensure prior stores are visible */
    __sync_fetch_and_add(&sl->seq, 1); /* make counter even again */
    preempt_enable();                /* re‑enable preemption */
}
```

The `preempt_disable()`/`preempt_enable()` pair is common when the protected data lives in per‑CPU memory; otherwise the writer may simply rely on the memory barriers.

### Reader Path: Optimistic Reads

A reader performs three steps:

1. Capture the current sequence number.
2. Read the data *without* taking any lock.
3. Re‑capture the sequence number and verify that it matches the first capture and is even.

```c
unsigned int read_seqbegin(const struct seqlock *sl)
{
    unsigned int seq;
    do {
        seq = READ_ONCE(sl->seq);
        /* If seq is odd, a writer is in progress – retry. */
    } while (seq & 1);
    return seq;
}

bool read_seqretry(const struct seqlock *sl, unsigned int start_seq)
{
    /* If the counter changed, the read was invalid. */
    return READ_ONCE(sl->seq) != start_seq;
}
```

In practice the kernel wraps these in inline helpers `read_seqbegin()` and `read_seqretry()`. The reader loop typically looks like:

```c
unsigned int seq;
do {
    seq = read_seqbegin(&my_seqlock);
    /* Copy data into a local struct */
    data = my_shared_data;
} while (read_seqretry(&my_seqlock, seq));
```

If the data changes while the reader is copying, the sequence number will differ, causing the loop to repeat. Because most reads succeed on the first try, the overhead is essentially a single `READ_ONCE` and a cheap parity test.

## How the Kernel Implements Seqlocks

The Linux kernel provides a small but well‑documented API for seqlocks, defined in `include/linux/seqlock.h`. The primary primitives are:

| Function | Purpose |
|----------|---------|
| `write_seqlock(seqlock_t *sl)` | Acquire write lock (increments to odd). |
| `write_sequnlock(seqlock_t *sl)` | Release write lock (increments to even). |
| `read_seqbegin(const seqlock_t *sl)` | Capture start sequence (retry if odd). |
| `read_seqretry(const seqlock_t *sl, unsigned int start)` | Validate after read. |
| `read_seqcount_begin(const seqlock_t *sl)` | Variant returning `unsigned long`. |
| `read_seqcount_retry(const seqlock_t *sl, unsigned long start)` | Variant for `unsigned long`. |

These macros expand to architecture‑specific barrier instructions, ensuring proper ordering on weakly ordered CPUs like ARM or PowerPC.

### Example: Updating a Network Statistics Counter

Consider the per‑CPU network statistics structure `struct rtnl_link_stats64`. The kernel updates it under a seqlock to allow lock‑free reads from tools like `ifconfig`:

```c
static SEQLOCK_DEFINE(net_stats_lock);
static struct rtnl_link_stats64 net_stats;

void netdev_update_stats(struct net_device *dev)
{
    write_seqlock(&net_stats_lock);
    net_stats.rx_packets += dev->stats.rx_packets;
    net_stats.tx_packets += dev->stats.tx_packets;
    /* other fields … */
    write_sequnlock(&net_stats_lock);
}

void netdev_get_stats(struct rtnl_link_stats64 *out)
{
    unsigned int seq;
    do {
        seq = read_seqbegin(&net_stats_lock);
        *out = net_stats;  /* struct copy – cheap */
    } while (read_seqretry(&net_stats_lock, seq));
}
```

The reader copies the entire struct in one go; if a writer sneaks in during the copy, the sequence number changes and the loop retries. Because the copy is usually a handful of 64‑bit loads, the probability of conflict is tiny, and the read path remains lock‑free.

## Performance Characteristics

### When Seqlocks Shine

* **Read‑dominant workloads** – e.g., per‑CPU counters, network statistics, scheduler load averages.
* **Small, fixed‑size data** – copying a struct is cheaper than acquiring a lock.
* **Low write contention** – if writes are infrequent, the chance of a reader retry is minimal.

Benchmarks in the LWN article *“Optimistic locking in the Linux kernel”* show seqlocks delivering up to 2‑3× higher read throughput than spinlocks on a 64‑core system when the write rate is below 1 % of the read rate.

### Hidden Costs and Pitfalls

1. **Starvation of Writers** – Readers may retry indefinitely under extreme read pressure, delaying the writer’s `write_seqend`. The kernel mitigates this by forcing a preemptible section in the writer path, but pathological cases still exist.
2. **Non‑retryable Reads** – If the protected data contains pointers that can be freed concurrently, a reader might dereference a stale pointer before detecting the change, leading to use‑after‑free bugs. Seqlocks are **not** a substitute for RCU in such scenarios.
3. **Wrap‑around Edge Cases** – Although rare, a 32‑bit counter can overflow while a reader is inside the loop, causing a false negative. The kernel’s implementation treats the overflow as a normal change, so the reader simply retries.
4. **Cacheline Contention on the Counter** – The `seq` field itself becomes a hot cache line under heavy write activity. In practice, this is acceptable because writes are infrequent; otherwise, per‑CPU seqlocks can be deployed.

## Correct Usage Patterns

### When Not to Use Seqlocks

* **Data with pointers to mutable objects** – Use RCU or hazard pointers instead.
* **Write‑heavy structures** – The writer will spend most of its time incrementing the counter, eroding the benefits.
* **Complex update logic requiring rollback** – Seqlocks assume writes are atomic from the reader’s perspective; partial updates can corrupt the data view.

### Integrating with RCU and SRCU

Sometimes a subsystem needs both optimistic reads and safe reclamation. A common pattern is to combine a seqlock for the fast path and RCU for memory safety:

```c
struct foo {
    struct rcu_head rcu;
    int value;
};

static SEQLOCK_DEFINE(foo_lock);
static struct foo *global_foo;

void foo_update(int new_val)
{
    struct foo *new = kmalloc(sizeof(*new), GFP_KERNEL);
    new->value = new_val;
    write_seqlock(&foo_lock);
    rcu_assign_pointer(global_foo, new);
    write_sequnlock(&foo_lock);
    /* old pointer will be freed after a grace period */
    synchronize_rcu();  // or call call_rcu() for async free
}
```

Readers use the seqlock to ensure they see a consistent snapshot, then dereference the pointer under `rcu_dereference()` to guarantee it isn’t reclaimed mid‑read.

## Key Takeaways

- **Seqlocks provide lock‑free reads** by using a monotonically increasing sequence counter that writers update twice per modification.
- **Readers validate** the data by checking that the counter is unchanged and even; a mismatch forces a retry, which is cheap when contention is low.
- **Best suited for small, read‑heavy structures** where the cost of copying the data is lower than acquiring a lock.
- **Not a replacement for RCU** when pointers to reclaimable memory are involved; combine both mechanisms for safety.
- **Watch out for writer starvation** and cache‑line hotness on the counter; consider per‑CPU seqlocks or alternative synchronisation if writes become frequent.

## Further Reading

- [Linux Kernel Documentation – Seqlocks](https://www.kernel.org/doc/html/latest/locking/seqlocks.html)  
- [LWN.net – Optimistic locking in the Linux kernel](https://lwn.net/Articles/447796/)  
- [The Celery docs – Memory barriers (relevant for seqlock ordering)](https://docs.celeryq.dev)  
- [Understanding RCU – Kernel.org article](https://www.kernel.org/doc/html/latest/rcu/rcu.html)  

---