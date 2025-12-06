---
title: "Memory-Mapped Files (mmap): A Practical Guide to Faster I/O and Shared Memory"
date: "2025-12-06T19:32:02.141"
draft: false
tags: ["mmap", "linux", "systems-programming", "performance", "memory-management"]
---

## Introduction

Memory-mapped files (mmap) let you treat file contents (or anonymous memory) as a region of your process’s virtual memory. Instead of calling read/write in loops, you map a file, then access it as if it were an in-memory buffer. The kernel transparently brings pages into RAM on demand and writes them back when needed. This can reduce system calls, enable zero-copy I/O, and open up powerful patterns like inter-process shared memory.

In this guide, we’ll cover how mmap works, when to use it, how to use it correctly and safely, and advanced tuning for performance-critical systems.

> TL;DR
> - mmap turns file I/O into memory access with demand paging and copy-on-write.
> - It can be faster and simpler for large or random access workloads, but comes with pitfalls (SIGBUS on truncation, consistency semantics, and tricky durability).
> - For shared memory or zero-copy parsing, mmap is often the right tool. For small synchronous writes, conventional I/O may be simpler and safer.

## Table of Contents

- [How mmap Works](#how-mmap-works)
- [API Basics: Signatures, Protections, and Flags](#api-basics-signatures-protections-and-flags)
- [File-Backed Mappings](#file-backed-mappings)
- [Anonymous Mappings and Shared Memory](#anonymous-mappings-and-shared-memory)
- [Synchronization and Durability](#synchronization-and-durability)
- [Error Handling and Signals](#error-handling-and-signals)
- [Performance Characteristics and Trade-offs](#performance-characteristics-and-trade-offs)
- [C Examples](#c-examples)
  - [Read-Only Mapping of a File](#read-only-mapping-of-a-file)
  - [Shared Memory Between Processes](#shared-memory-between-processes)
- [Python Example](#python-example)
- [Advanced Tuning: madvise, mlock, Huge Pages, NUMA](#advanced-tuning-madvise-mlock-huge-pages-numa)
- [Filesystem and Environment Caveats](#filesystem-and-environment-caveats)
- [Portability Notes (Windows)](#portability-notes-windows)
- [Debugging and Profiling](#debugging-and-profiling)
- [Security Considerations](#security-considerations)
- [Common Pitfalls Checklist](#common-pitfalls-checklist)
- [When Not to Use mmap](#when-not-to-use-mmap)
- [Conclusion](#conclusion)

## How mmap Works

At a high level:
- The kernel installs a virtual memory mapping that associates a range of your process’s virtual addresses with pages in the page cache (for files) or anonymous memory.
- When your code accesses an address that’s not in RAM yet, the CPU takes a page fault. The kernel loads the page from disk (or zero-fills it for anonymous memory) and resumes your process.
- With `MAP_PRIVATE`, writes are copy-on-write: your changes do not affect the underlying file and are stored in a private anonymous page.
- With `MAP_SHARED`, modifications can be visible to other processes mapping the same file and can be persisted to disk via write-back or `msync`.

This design:
- Avoids extra data copies (you read/write directly from/to the page cache).
- Eliminates many syscalls (no read/write loops).
- Enables random access patterns naturally (pointer arithmetic).

But it also means:
- Latency is hidden in page faults.
- Memory access may signal fatal errors (e.g., `SIGBUS` if you touch a page beyond EOF due to truncation).
- Durability and ordering guarantees differ from write/fsync.

## API Basics: Signatures, Protections, and Flags

POSIX/Linux prototype:
```c
#include <sys/mman.h>

void *mmap(void *addr, size_t length, int prot, int flags, int fd, off_t offset);
int munmap(void *addr, size_t length);
int msync(void *addr, size_t length, int flags);
int mprotect(void *addr, size_t len, int prot);
```

Key parameters:
- addr: Preferred address (usually NULL—let the kernel choose).
- length: Number of bytes to map (rounded up to page size).
- prot: Protections: `PROT_READ`, `PROT_WRITE`, `PROT_EXEC`, `PROT_NONE`.
- flags: Mapping type and behavior.
  - `MAP_PRIVATE` (copy-on-write, changes not visible to others)
  - `MAP_SHARED` (changes visible and can be persisted)
  - `MAP_ANONYMOUS` (no file; use fd = -1)
  - `MAP_FIXED` (force mapping at addr; dangerous—can clobber existing mappings)
  - `MAP_FIXED_NOREPLACE` (safer: fails if region occupied; Linux 4.17+)
  - `MAP_POPULATE` (prefault pages proactively)
  - `MAP_NORESERVE` (don’t reserve swap; may OOM later on write)
  - `MAP_HUGETLB` / `MAP_HUGE_2MB`, etc. (explicit huge pages; privileged environments)
- fd: File descriptor (unless `MAP_ANONYMOUS`).
- offset: Byte offset in file (must be multiple of page size).

> Note
> - Offsets and lengths are page-aligned internally. If you need a sub-page region, you must adjust your base pointer and track an intra-page offset.

## File-Backed Mappings

Use cases:
- Fast reads of large files (databases, logs, machine learning datasets).
- Random access into large structured files (indexes, memory-mapped key-value stores).
- Zero-copy parsing and tokenization.

Key behaviors:
- Read-only (`PROT_READ|MAP_PRIVATE`) is simplest and safest.
- Shared writeable (`PROT_WRITE|MAP_SHARED`) allows cross-process data sharing and persistence but requires careful synchronization and msync.

Coherency:
- The mapping reflects the page cache, which is also used by read/write syscalls. Updates via either path are coherent at the page-cache level, but you must consider visibility timing and ordering:
  - Readers and writers in different processes need explicit synchronization (e.g., locks, atomics) to define when data is ready.
  - To push changes to disk, use `msync` and potentially `fsync`/`fdatasync` for metadata (like size changes).

Resizing files:
- If another process truncates the file shorter than your mapping, accessing the truncated area can deliver `SIGBUS`.
- If you need to grow a file for a mapping, `ftruncate` first, then `mmap` the new length.

## Anonymous Mappings and Shared Memory

Anonymous mappings (`MAP_ANONYMOUS`) allocate memory not backed by a file. They are:
- Great for large heaps that you want to grow/shrink with `mmap/munmap` rather than `malloc`.
- Useful for shared memory regions when combined with `MAP_SHARED` and a shared file descriptor (e.g., a file on tmpfs `/dev/shm`, `memfd_create`, or POSIX shared memory objects via `shm_open`).

To share:
- Two processes can map the same file descriptor with `MAP_SHARED`.
- Use IPC coordination (futexes, pthread mutexes with `PTHREAD_PROCESS_SHARED`, POSIX semaphores, or atomics) to handle visibility and ordering.

> Note
> - Anonymous `MAP_SHARED` without an actual file descriptor is not portable. On Linux, `MAP_ANONYMOUS|MAP_SHARED` is shared only with forked children (inherits mapping); for unrelated processes, use a shared fd via `shm_open`, `memfd_create`, or a real file.

## Synchronization and Durability

- msync:
  - `msync(addr, len, MS_SYNC)`: Block until dirty pages in range are flushed to storage.
  - `MS_ASYNC`: Schedule flush; returns sooner.
  - `MS_INVALIDATE`: Invalidate caches to re-read from disk (rarely needed for typical workflows).
- fsync/fdatasync:
  - Ensure on-disk metadata (like size) is durable. After `ftruncate`, call `fsync` on the file descriptor.
- DAX/PMEM:
  - On persistent memory with direct access (DAX), `MAP_SYNC` and instructions like `clwb`/`sfence` are used under the hood; consult filesystem/PMEM docs.

Ordering with readers:
- Use explicit memory barriers/atomics around “ready” flags, not msync, to coordinate inter-process readers observing consistent data structures.

## Error Handling and Signals

- SIGBUS: Accessing an unmapped page due to I/O error or file truncation raises `SIGBUS`. Catchable but often fatal; design to avoid it (locks, size checks, stable files).
- SIGSEGV: Accessing outside the mapped range or violating `PROT_*` protections.
- ENOMEM: If the kernel cannot map pages (address space fragmentation or overcommit disabled).
- EINVAL: Unaligned offset, invalid flags, or length 0.

> Note
> - Don’t rely on EFAULT-like error codes for bad accesses—the fault happens lazily at use time, not mmap time.

## Performance Characteristics and Trade-offs

Advantages:
- Zero-copy reads/writes via the page cache.
- Fewer syscalls and kernel-user copies.
- Natural random access by pointer.

Costs and caveats:
- Page-fault latency can cause unpredictable stalls.
- Small scattered writes may cause many dirty pages and writeback overhead.
- For write-heavy workloads, explicit buffered I/O with carefully sized write calls can be more predictable.
- On network filesystems, semantics can differ and performance can be surprising.

Access patterns:
- Sequential read: Use `MADV_SEQUENTIAL`.
- Random read: Default is fine; consider readahead tuning or application-level prefetch.
- One-shot scan: `MADV_DONTNEED` after use can free page cache sooner.

NUMA:
- First-touch policy applies. Prefaulting or binding threads to nodes can improve locality.

## C Examples

### Read-Only Mapping of a File

This example maps an entire file read-only and computes a simple checksum.

```c
#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
#include <stdlib.h>

static void die(const char *msg) {
    perror(msg);
    exit(EXIT_FAILURE);
}

int main(int argc, char **argv) {
    if (argc != 1 + 1) {
        fprintf(stderr, "Usage: %s <path>\n", argv[0]);
        return 2;
    }

    const char *path = argv[1];
    int fd = open(path, O_RDONLY);
    if (fd < 0) die("open");

    struct stat st;
    if (fstat(fd, &st) < 0) die("fstat");
    size_t length = (size_t)st.st_size;
    if (length == 0) {
        printf("Empty file\n");
        close(fd);
        return 0;
    }

    void *addr = mmap(NULL, length, PROT_READ, MAP_PRIVATE
#ifdef MAP_POPULATE
                      | MAP_POPULATE
#endif
                      , fd, 0);
    if (addr == MAP_FAILED) die("mmap");

    const unsigned char *p = (const unsigned char *)addr;
    uint64_t sum = 0;
    for (size_t i = 0; i < length; i++) {
        sum += p[i];
    }
    printf("Checksum: %llu\n", (unsigned long long)sum);

    if (munmap(addr, length) < 0) die("munmap");
    close(fd);
    return 0;
}
```

Notes:
- We use `_FILE_OFFSET_BITS=64` to handle large files on 32-bit builds.
- `MAP_POPULATE` reduces first-access page faults at the cost of startup latency.

### Shared Memory Between Processes

Below, a writer creates a shared region using `shm_open` and a reader maps the same region. They coordinate with a POSIX named semaphore.

Writer (producer):

```c
#define _GNU_SOURCE
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <semaphore.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define SHM_NAME "/my_shm_example"
#define SEM_NAME "/my_shm_sem"
#define SIZE 4096

int main(void) {
    int fd = shm_open(SHM_NAME, O_CREAT | O_RDWR, 0600);
    if (fd < 0) { perror("shm_open"); exit(1); }
    if (ftruncate(fd, SIZE) < 0) { perror("ftruncate"); exit(1); }

    char *mem = mmap(NULL, SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (mem == MAP_FAILED) { perror("mmap"); exit(1); }

    sem_t *sem = sem_open(SEM_NAME, O_CREAT, 0600, 0);
    if (sem == SEM_FAILED) { perror("sem_open"); exit(1); }

    const char *msg = "hello from shared memory";
    memcpy(mem, msg, strlen(msg) + 1);

    // Ensure visibility to other processes (cache coherence is maintained,
    // but the semaphore orders publication).
    if (sem_post(sem) < 0) { perror("sem_post"); }

    // Optional durability if the object were backed by a real file:
    // msync(mem, SIZE, MS_SYNC);

    munmap(mem, SIZE);
    close(fd);
    // Cleanup left to system or separate cleanup tool:
    // shm_unlink(SHM_NAME); sem_unlink(SEM_NAME);
    return 0;
}
```

Reader (consumer):

```c
#define _GNU_SOURCE
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <semaphore.h>
#include <stdio.h>
#include <stdlib.h>

#define SHM_NAME "/my_shm_example"
#define SEM_NAME "/my_shm_sem"
#define SIZE 4096

int main(void) {
    int fd = shm_open(SHM_NAME, O_RDONLY, 0600);
    if (fd < 0) { perror("shm_open"); exit(1); }
    char *mem = mmap(NULL, SIZE, PROT_READ, MAP_SHARED, fd, 0);
    if (mem == MAP_FAILED) { perror("mmap"); exit(1); }

    sem_t *sem = sem_open(SEM_NAME, 0);
    if (sem == SEM_FAILED) { perror("sem_open"); exit(1); }

    if (sem_wait(sem) < 0) { perror("sem_wait"); }

    printf("Reader saw: %s\n", mem);

    munmap(mem, SIZE);
    close(fd);
    return 0;
}
```

> Note
> - `shm_open` creates an object in a special namespace (often backed by tmpfs). Use `shm_unlink` and `sem_unlink` to remove named objects when done.

## Python Example

Python’s `mmap` module provides a convenient wrapper:

```python
import mmap
import os

def mmap_readonly(path: str) -> int:
    total = 0
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size == 0:
            return 0
        with mmap.mmap(f.fileno(), length=0, access=mmap.ACCESS_READ) as mm:
            # length=0 maps the entire file on many platforms
            # Simple sum to touch all bytes
            total = sum(mm)
    return total

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <file>")
        sys.exit(2)
    print(mmap_readonly(sys.argv[1]))
```

For shared mappings in Python:
- Use `mmap.mmap(fd, length, access=mmap.ACCESS_WRITE)` with a file descriptor opened read-write.
- Coordinate with `multiprocessing` synchronization primitives (Locks, Events) or POSIX semaphores via `ctypes`/third-party libraries.

## Advanced Tuning: madvise, mlock, Huge Pages, NUMA

- madvise:
  - `MADV_SEQUENTIAL`: Kernel readahead is more aggressive.
  - `MADV_RANDOM`: Disable readahead.
  - `MADV_WILLNEED`: Prefetch pages.
  - `MADV_DONTNEED`: Discard clean pages from the page cache after use.
  - `MADV_REMOVE` (on tmpfs): Punch holes in files (like `fallocate` with punch-hole).
- mlock/mlockall: Pin pages in RAM to avoid paging; requires privileges and can harm system stability if overused.
- Huge pages:
  - Transparent Huge Pages (THP) may coalesce 4KB pages automatically. For more control, use `MAP_HUGETLB` (requires pre-allocated huge pages and privileges).
- NUMA:
  - Use `numactl` or `mbind`/`set_mempolicy` to place memory near the CPU using it.
  - First-touch dictates page placement; consider prefaulting with `MAP_POPULATE` and touching pages in the target thread.

## Filesystem and Environment Caveats

- Network filesystems (NFS/SMB):
  - Coherency and caching semantics can differ; concurrent modifications by other clients may be surprising. Some setups disable mmap or degrade performance.
- File truncation and growth:
  - If a mapped file is truncated smaller, any access beyond new EOF can cause `SIGBUS`.
  - To grow, `ftruncate` first, then map or remap the new size (on Linux: `mremap` can expand).
- Sparse files:
  - Reading a sparse hole yields zeros; writing may allocate blocks.
- Direct I/O:
  - `O_DIRECT` bypasses the page cache and is generally incompatible with mmap. If you need direct I/O semantics, stick to read/write.
- DAX (Direct Access):
  - On filesystems supporting DAX (pmem), mappings bypass the page cache. Durability and ordering require special care (`MAP_SYNC`, flush instructions under the hood).

## Portability Notes (Windows)

Windows provides similar APIs:
- CreateFile → CreateFileMapping → MapViewOfFile (and UnmapViewOfFile).
- Protection and access flags differ; offsets must align to the system allocation granularity.
- Flushing:
  - FlushViewOfFile for pages; FlushFileBuffers to ensure file durability.
- The Python `mmap` module works on Windows with minor differences (e.g., tag names).

## Debugging and Profiling

- strace: Observe `mmap`, `pagefault`s (minor/major via perf), `msync`, etc.
- perf:
  - `perf stat -e page-faults,major-faults` to quantify fault costs.
  - `perf record` + `perf report` to study hotspots.
- /proc:
  - `/proc/<pid>/maps`, `/proc/<pid>/smaps` show mappings and residency.
  - `mincore()` can query which pages are resident.
- valgrind:
  - Useful for catching invalid memory access patterns; keep in mind lazy faults.
- ftrace/bpf:
  - Deeper kernel insights into reclaim/writeback if you chase stalls.

## Security Considerations

- Least privilege:
  - Don’t map writable and executable at the same time (W^X policy).
  - Use `PROT_READ` for read-only mappings whenever possible.
- Avoid `MAP_FIXED` unless you must. Prefer `MAP_FIXED_NOREPLACE` to avoid clobbering existing regions.
- Sanitizing inputs:
  - Don’t trust file contents; treat them like untrusted input even if “in memory.” Parsing should include bounds checks.
- Address space and ASLR:
  - Large mappings can reduce address space entropy in 32-bit or constrained environments.
- Overcommit/NORESERVE:
  - `MAP_NORESERVE` can lead to crashes under memory pressure when a COW page cannot be allocated.

## Common Pitfalls Checklist

- Access after truncate: Protect mapped files from concurrent shrinking; use file locks or versioning.
- Assuming msync orders readers: Use explicit synchronization (atomics, semaphores) for publication.
- Off-by-one on length or misaligned offsets: Ensure offset is `page_size` aligned and access stays within `length`.
- Mixing O_DIRECT with mmap: Generally incompatible.
- Expecting immediate durability without `msync`/`fsync`: Write-back is asynchronous by default.
- Ignoring EINTR or partial effects: While `mmap`/`munmap` are atomic, surrounding syscalls (like open/ftruncate) require normal care.
- Mapping huge files on 32-bit: You may run out of virtual address space.

## When Not to Use mmap

- Tiny files or small writes where a simple `read`/`write` is clearer and fast enough.
- High-frequency, latency-sensitive writes where controlling I/O scheduling is critical.
- Environments with problematic network filesystems or strict durability semantics that are easier with explicit `write+fsync`.
- When you cannot manage the risk of `SIGBUS` on concurrent truncate.

## Conclusion

mmap is a powerful abstraction that can simplify code, improve I/O performance, and unlock efficient inter-process communication. By letting the kernel manage paging and caching, you gain zero-copy access and natural random reads. However, it’s not a silver bullet: you must handle synchronization, durability, and edge cases like file truncation and page faults.

Use read-only mappings for analytics and parsing; use shared mappings plus proper synchronization for IPC; and apply advanced controls like `madvise`, `mlock`, and huge pages when profiling shows benefits. With careful design, mmap can be a cornerstone of fast, robust systems programming.

