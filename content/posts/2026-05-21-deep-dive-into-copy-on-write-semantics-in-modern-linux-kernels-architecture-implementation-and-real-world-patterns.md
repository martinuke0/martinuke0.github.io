---
title: "Deep Dive into Copy-on-Write Semantics in Modern Linux Kernels: Architecture, Implementation, and Real-World Patterns"
date: "2026-05-21T13:01:04.499"
draft: false
tags: ["Linux", "Copy-on-Write", "Kernel", "Performance", "Systems"]
description: "Explore how modern Linux kernels implement copy-on-write, its architecture, key data structures, and production patterns that boost performance and safety."
summary: "A technical walkthrough of Linux’s copy‑on‑write mechanism, from page‑fault handling to real‑world deployment patterns."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-21-deep-dive-into-copy-on-write-semantics-in-modern-linux-kernels-architecture-implementation-and-real-world-patterns.svg"
  alt: "Diagram of shared memory pages with copy-on-write arrows."
  caption: ""
  relative: false
---

> **TL;DR** — Copy‑on‑Write (CoW) in Linux isolates writes by sharing pages until a fault, saving memory and I/O; the kernel’s page‑fault path, `mm_struct`, and KSM illustrate its architecture, while production patterns like container image layering and database snapshots leverage CoW for efficiency and safety.

Copy‑on‑Write is one of the quiet workhorses that lets Linux scale from tiny embedded devices to massive cloud fleets. When a process forks, the kernel can expose the same physical pages to both parent and child, postponing the actual copy until one of them tries to modify the data. That single design decision ripples through memory management, file systems, containers, and databases. In this post we unpack the kernel’s CoW plumbing, walk through the critical code paths, and then map those mechanisms onto the patterns you’ll see in production today.

## Foundations of Copy‑on‑Write

### Historical Context

The original Unix `fork()` semantics were already CoW‑enabled in the early 1970s, but the implementation was a simple reference‑count bump on each page table entry. Over the decades, Linux added layers of sophistication:

| Kernel Release | Key CoW‑related Feature |
|----------------|--------------------------|
| 2.4            | Basic `fork()` page sharing |
| 2.6            | `mm_struct` ref‑counting, `VM_MAYSHARE` flag |
| 3.0            | Transparent Huge Pages (THP) integration |
| 4.9            | Kernel Samepage Merging (KSM) |
| 5.10           | `mprotect`‑based CoW for user‑space libraries |

These milestones show how CoW evolved from a fork‑only trick to a general‑purpose memory‑efficiency primitive.

### Core Data Structures

At the heart of CoW lie three structures:

* **`struct page`** – represents a physical frame; contains `refcount` and flags like `PG_dirty`.
* **`struct vm_area_struct` (VMA)** – describes a contiguous virtual address range; flags such as `VM_SHARED` and `VM_MAYWRITE` guide CoW decisions.
* **`struct mm_struct`** – the address space descriptor for a process; holds the page tables, a list of VMAs, and a `pgd_t *pgd` root.

When a fork occurs, the kernel copies the parent’s `mm_struct` (shallowly) and marks every VMA as **read‑only** for the child. The `page` refcount is atomically incremented, turning the shared pages into CoW candidates.

## Architecture in the Modern Kernel

### Page Fault Path

The moment a process writes to a read‑only page, the CPU raises a protection fault. The kernel’s entry point is `do_page_fault()` (found in `mm/memory.c`). The high‑level flow is:

1. **Validate the fault** – check user vs kernel mode, address legality.
2. **Locate the VMA** – `find_vma()` walks the red‑black tree of VMAs.
3. **Determine CoW eligibility** – `vma->vm_flags & VM_MAYWRITE` and `page->refcount > 1`.
4. **Allocate a new page** – `alloc_page()` from the appropriate zone.
5. **Copy contents** – `copy_page()` or `memcpy` for THP.
6. **Update page tables** – `pte_mkwrite()` and `pte_mkold()` to make the new mapping writable.
7. **Release the old page** – decrement refcount; if it hits zero, the page is reclaimed.

A simplified pseudo‑code version:

```c
int handle_cow_fault(struct vm_area_struct *vma, unsigned long address)
{
    struct page *old_page, *new_page;
    pte_t *pte = get_pte(vma->vm_mm, address);
    old_page = pte_page(*pte);

    if (page_ref_count(old_page) == 1)
        return 0; // No need to copy

    new_page = alloc_page(GFP_KERNEL);
    if (!new_page)
        return -ENOMEM;

    copy_page(new_page, old_page);
    set_pte_at(vma->vm_mm, address, pte, mk_pte(new_page, vma->vm_page_prot));
    page_ref_dec(old_page);
    return 0;
}
```

The real kernel code is more defensive (RCU, lock‑less lookups, NUMA awareness), but the essence is captured above.

### `mm_struct` and VMA Flags

The `mm_struct` holds a **copy‑on‑write bitmap** (`mm->cow_page_state`) that tracks which pages have already been duplicated during a given fault handling window. This prevents double‑copying when the same page is faulted multiple times in rapid succession.

Key VMA flags:

| Flag | Meaning |
|------|---------|
| `VM_SHARED` | Mapping is shared across processes; CoW is *not* applied for writes (e.g., mmap‑ed files). |
| `VM_MAYWRITE` | Process *may* write; kernel checks this before allowing a write fault. |
| `VM_WRITE` | Write permission already granted (used after successful CoW). |
| `VM_PFNMAP` | Page‑frame-number mapping; bypasses normal page structures, CoW not applicable. |

When `fork()` clones the address space, the kernel clears `VM_WRITE` on the child’s VMAs, forcing the first write to trigger the CoW path.

### Kernel Samepage Merging (KSM)

KSM is a background daemon (`ksmd`) that scans anonymous memory for identical pages, then merges them into a single **copy‑on‑write** page. The algorithm works like this:

1. **Hashing** – each page’s content is hashed (SHA‑1 or xxHash) and placed into a **radix tree**.
2. **Deduplication** – when two pages share the same hash, `ksm_scan_process()` calls `ksm_merge_page()` to replace both with a shared `struct page`.
3. **Reference counting** – the merged page’s refcount grows; any subsequent write fault triggers the standard CoW path, automatically splitting the page.

KSM is especially valuable for VMs running the same OS image, or for containers that share large read‑only libraries.

## Implementation Details

### Copy‑on‑Write on `fork()`

The `do_fork()` function (in `kernel/fork.c`) orchestrates the whole process:

```c
long do_fork(unsigned long clone_flags,
             unsigned long stack_start,
             unsigned long stack_size,
             int __user *parent_tidptr,
             int __user *child_tidptr,
             unsigned long tls)
{
    struct task_struct *p;
    struct mm_struct *mm = current->mm;
    struct mm_struct *mm_new;

    mm_new = mmdup(mm);               // shallow copy, increments page refcounts
    if (IS_ERR(mm_new))
        return PTR_ERR(mm_new);

    // Mark child VMAs read‑only
    mprotect_fixup(mm_new, 0, TASK_SIZE, PROT_READ);
    // Continue with task creation...
}
```

`mmdup()` walks each VMA, clones the VMA structure, and calls `page_dup_rmap()` to bump the page’s refcount. The child’s page tables are initially **identical**, but every writable VMA is cleared of the write flag, ensuring the first write triggers the fault path described earlier.

### Transparent Huge Pages (THP) and CoW

When THP is enabled (`/sys/kernel/mm/transparent_hugepage/enabled`), the kernel tries to allocate 2 MiB pages instead of 4 KiB pages. CoW on THP follows the same principles, but the copy operation must move an entire huge page, which is more expensive. The kernel therefore prefers **splitting** a huge page into base pages before copying, unless the whole huge page is being written.

Relevant code lives in `mm/huge_memory.c`:

```c
int copy_huge_page(struct page *src, struct page *dst)
{
    // Use the hardware‑accelerated copy if available (e.g., CLFLUSH)
    return __copy_huge_page(src, dst);
}
```

Production workloads often disable THP for databases that perform many small writes, to avoid the cost of copying entire 2 MiB pages on a single byte modification.

### Synchronization and RCU

Because the page‑fault path runs on the fast path of every write, it cannot afford heavyweight locks. The kernel uses **RCU (Read‑Copy‑Update)** to protect the page tables while still allowing concurrent readers. The `pte_lock` spinlock is held only for the brief moment of updating the PTE; the rest of the algorithm proceeds lock‑free.

```c
spin_lock(&ptl->pte_lock);
set_pte_at(mm, address, pte, new_pte);
spin_unlock(&ptl->pte_lock);
```

RCU guarantees that any CPU still holding a reference to the old PTE will see a consistent view until it reaches an RCU grace period, after which the old page can be reclaimed.

## Patterns in Production

### Container Image Layering

Docker and OCI images are built as **read‑only layers** stacked on top of each other. When a container starts, the container runtime mounts each layer using a **copy‑on‑write overlay filesystem** (`overlayfs`). The underlying layers are shared across all containers, and only the topmost writable layer incurs actual copies.

* **Benefit** – Thousands of containers can run the same base image while consuming a single copy of each library file.
* **Implementation** – `overlayfs` uses CoW at the file‑system level: a write to a file creates a new copy in the upper layer, while reads continue to hit the lower read‑only layers.

### Database Snapshots (PostgreSQL, MySQL InnoDB)

PostgreSQL’s MVCC (Multi‑Version Concurrency Control) relies on **snapshot isolation**, which is essentially a logical CoW on rows. Internally, the storage engine uses **write‑ahead logs** and **page‑level CoW**:

* When a transaction updates a row, the page containing that row is duplicated (or a new version is appended), and the old version remains visible to other transactions.
* The kernel’s anonymous memory CoW complements this by allowing the database process to `fork()` for hot‑standby or logical replication without duplicating the entire buffer pool.

MySQL’s InnoDB employs a similar technique, using **undo logs** that act as CoW copies of the original data.

### Virtual Machine Live Migration

Live migration moves a running VM from one host to another with minimal downtime. The typical approach:

1. **Pre‑copy** – The source host streams the VM’s memory pages to the destination while the VM continues running.
2. **Dirty‑page tracking** – The kernel’s **userfaultfd** or **KVM dirty‑bitmap** marks pages that have been written to (CoW‑style tracking).
3. **Final sync** – After a few rounds, only the dirty pages (the ones that triggered CoW) are transferred.

Because the VM’s memory is largely read‑only during the pre‑copy phase, the CoW mechanism drastically reduces the amount of data that must be shipped in the final cutover.

## Performance Considerations and Failure Modes

* **Cache Pressure** – Frequent CoW faults flush caches, leading to higher latency. Monitoring `majflt` (major page faults) and `minflt` (minor page faults) per process helps identify hot spots.
* **OOM Risks** – In memory‑constrained environments, a sudden burst of writes after a large `fork()` can cause an **out‑of‑memory** event because the kernel must allocate new pages for each faulted write. Using `cgroup` memory limits and `ulimit -v` can mitigate surprise OOM kills.
* **THP Pitfalls** – As noted, THP can turn a single‑byte write into a 2 MiB copy. Disabling THP (`echo never > /sys/kernel/mm/transparent_hugepage/enabled`) for write‑heavy workloads is a common production tweak.
* **KSM Overhead** – KSM’s background scanning consumes CPU cycles and can interfere with latency‑sensitive applications. Tuning `/sys/kernel/mm/ksm/run` and `/sys/kernel/mm/ksm/pages_to_scan` helps balance deduplication benefits against CPU cost.

## Key Takeaways

- **CoW is a kernel‑level optimization** that postpones copying until a write occurs, saving memory and I/O across forks, containers, and snapshots.
- The **page‑fault path** (`do_page_fault`) is the critical hot path; it uses reference counting, lock‑less lookups, and RCU to stay fast.
- **`mm_struct`, VMAs, and `struct page`** work together to track sharing and decide when to duplicate.
- **KSM** extends CoW to anonymous memory that was not originally shared, enabling massive deduplication for identical workloads.
- Real‑world systems—**Docker overlayfs, PostgreSQL MVCC, VM live migration**—build on top of CoW to achieve rapid provisioning, low‑cost snapshots, and near‑zero‑downtime moves.
- Tuning **THP, KSM, and memory limits** is essential to avoid hidden latency spikes or OOM failures in production environments.

## Further Reading

- [Linux Kernel Documentation – Memory Management](https://www.kernel.org/doc/html/latest/v4.14/mm/index.html)  
- [Understanding Kernel Samepage Merging (KSM)](https://www.redhat.com/en/blog/understanding-kernel-samepage-merging-ksm)  
- [Docker Storage Drivers – OverlayFS](https://docs.docker.com/storage/storagedriver/overlayfs/)  
- [PostgreSQL MVCC Documentation](https://www.postgresql.org/docs/current/mvcc.html)  

---