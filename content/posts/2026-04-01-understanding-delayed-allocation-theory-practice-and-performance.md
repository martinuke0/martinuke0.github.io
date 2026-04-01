---
title: "Understanding Delayed Allocation: Theory, Practice, and Performance"
date: "2026-04-01T10:58:21.397"
draft: false
tags: ["filesystem", "performance", "Linux", "ext4", "storage"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [What Is Delayed Allocation?](#what-is-delayed-allocation)  
   - 2.1 [Historical Context](#historical-context)  
   - 2.2 [Core Principle](#core-principle)  
3. [How Modern Filesystems Implement Delayed Allocation](#how-modern-filesystems-implement-delayed-allocation)  
   - 3.1 [ext4](#ext4)  
   - 3.2 [XFS](#xfs)  
   - 3.3 [btrfs & ZFS](#btrfs--zfs)  
4. [Benefits of Delayed Allocation](#benefits-of-delayed-allocation)  
   - 4.1 [Write Aggregation & Throughput](#write-aggregation--throughput)  
   - 4.2 [Reduced Fragmentation](#reduced-fragmentation)  
   - 4.3 [Improved SSD Longevity](#improved-ssd-longevity)  
5. [Risks, Edge Cases, and Data‑Loss Scenarios](#risks-edge-cases-and-data‑loss-scenarios)  
6. [Tuning Delayed Allocation on Linux](#tuning-delayed-allocation-on-linux)  
   - 6.1 [Mount Options](#mount-options)  
   - 6.2 [sysctl Parameters](#sysctl-parameters)  
   - 6.3 [Application‑Level Strategies](#application‑level-strategies)  
7. [Practical Examples](#practical-examples)  
   - 7.1 [Benchmarking Write Patterns with `dd`](#benchmarking-write-patterns-with-dd)  
   - 7.2 [C Program Demonstrating `posix_fallocate` vs. Delayed Allocation](#c-program-demonstrating-posix_fallocate-vs-delayed-allocation)  
   - 7.3 [Monitoring with `iostat` and `blktrace`](#monitoring-with-iostat-and-blktrace)  
8. [Real‑World Use Cases](#real‑world-use-cases)  
   - 8.1 [Databases (MySQL, PostgreSQL)](#databases-mysql-postgresql)  
   - 8.2 [Virtual Machines & Containers](#virtual-machines--containers)  
   - 8.3 [Log‑Heavy Applications](#log‑heavy-applications)  
9. [Comparing Delayed Allocation to Other Allocation Strategies](#comparing-delayed-allocation-to-other-allocation-strategies)  
10. [Debugging & Troubleshooting](#debugging--troubleshooting)  
11 [Best Practices Checklist](#best-practices-checklist)  
12 [Future Directions and Emerging Trends](#future-directions-and-emerging-trends)  
13 [Conclusion](#conclusion)  
14 [Resources](#resources)  

---

## Introduction

When a program writes data to a file, the operating system must decide **where** on the storage medium to place those bytes.  Historically, the kernel performed this decision **immediately**, allocating disk blocks as soon as the first `write()` call arrived.  While simple, that approach often leads to sub‑optimal performance: many tiny allocations, fragmented files, and excessive I/O traffic.

Enter **delayed allocation**—a technique that postpones the actual block allocation until the data is about to be flushed to disk (typically at `fsync()`, `close()`, or when the filesystem’s journal is committed).  By aggregating writes, the filesystem gains a more holistic view of the file’s final size and layout, enabling smarter placement and dramatically reducing fragmentation.

This article provides a deep dive into delayed allocation: its origins, how it works in modern Linux filesystems, the performance gains you can expect, pitfalls to avoid, and concrete steps to tune it for production workloads.  Whether you are a system administrator, storage engineer, or application developer, understanding delayed allocation empowers you to extract maximum efficiency from the underlying hardware.

---

## What Is Delayed Allocation?

### Historical Context

Early Unix filesystems (e.g., the original ext2) allocated blocks **synchronously** with each `write()`.  The kernel’s VFS layer called the filesystem’s `allocate_blocks()` routine, which immediately reserved space on the disk bitmap and updated metadata.  The design was straightforward, but it suffered from three fundamental problems:

1. **Fragmentation** – Small, scattered writes caused files to be laid out in non‑contiguous clusters.
2. **Write Amplification** – Each allocation required a metadata update, generating additional I/O.
3. **Inefficient Use of Write‑Back Cache** – The kernel’s page cache could already coalesce writes, yet the filesystem forced early allocation, negating the cache’s benefits.

The first major change arrived with the **ext3** journal, which introduced delayed allocation as an optional feature.  Later, **ext4** made it the default, and other filesystems such as **XFS**, **btrfs**, and **ZFS** adopted similar mechanisms (often under different names, e.g., “extent allocation” or “space reservation”).

### Core Principle

At its core, delayed allocation works like this:

1. **Write Arrival** – The application calls `write(fd, buf, len)`.  
2. **Page Cache Buffering** – The kernel copies the data into a page cache page (or multiple pages). No blocks are reserved yet.  
3. **Dirty Marking** – The page is marked “dirty” and attached to the inode’s *dirty page list*.  
4. **Flush Trigger** – When the page cache decides to write back (because of memory pressure, a timer, or an explicit `fsync()`), the filesystem’s allocation routine is invoked.  
5. **Block Allocation** – At this point, the filesystem sees the *total* amount of data that will be written for the inode and can allocate a contiguous extent (or several large extents) that best fit the request.  
6. **Write‑back** – The data is finally written to the allocated blocks, and the journal (if present) records the new metadata.

Because the allocation step is deferred, the filesystem can **merge multiple writes** that belong to the same file, **choose larger extents**, and **avoid allocating space that may later be overwritten** (a common pattern in log files).

> **Important Note**  
> Delayed allocation does **not** mean “no allocation”.  The data is still safely stored in RAM until it is flushed.  The risk lies only in the window between the last write and the next `fsync()` (or crash), where data could be lost if the system crashes before the allocation occurs.

---

## How Modern Filesystems Implement Delayed Allocation

### ext4

ext4’s delayed allocation is built around three key structures:

| Structure | Role |
|-----------|------|
| **`extent_status_tree` (ES) ** | Tracks allocated extents for fast lookup. |
| **`i_allocated_data`** | Holds a list of pages that are pending allocation. |
| **`journal`** | Guarantees atomicity of metadata updates when the allocation finally occurs. |

The relevant mount options are:

- `delalloc` (default **on**) – Enable delayed allocation.
- `nodalloc` – Disable it (useful for benchmarking or low‑latency workloads that cannot tolerate the extra flush latency).

The allocation algorithm runs in `ext4_da_writepages()`.  It examines the total dirty size of an inode, calculates an optimal *allocation size* (typically a multiple of the filesystem’s `inode->i_blocksize`), and then calls `ext4_da_reserve_space()` to reserve the needed blocks in a single transaction.  The resulting extent is written to the journal before the actual data pages are dispatched to the block device.

### XFS

XFS uses the term **“delayed allocation”** as well, but its implementation is tightly coupled with its **allocation groups (AGs)** and **extent-based metadata**.  The main structures are:

- **`xfs_da_state`** – Holds pending allocation state.
- **`xfs_inode`** – Contains a per‑inode delayed allocation flag.

When a write occurs, XFS marks the corresponding **extent map** entry as “unallocated”.  The actual allocation happens in `xfs_delalloc_inode()` when the inode’s dirty pages are flushed.  XFS can also **reclaim space** from previously allocated but unwritten extents, a feature that helps to avoid “write‑hole” fragmentation.

### btrfs & ZFS

Both btrfs and ZFS employ **copy‑on‑write (CoW)** semantics, which inherently delay allocation: new data is always written to fresh blocks, and the old metadata is updated only after the write succeeds.  However, they still expose a form of delayed allocation:

- **btrfs** uses **extent allocation** that can be delayed until the transaction commit, controlled by the `delalloc` mount option (default on).  
- **ZFS** has a **“ZIL” (ZFS Intent Log)** that buffers synchronous writes, and the *actual* block allocation occurs when the transaction group (TXG) is synced (usually every 5 seconds).  

These designs make the concept of delayed allocation even more powerful because they combine it with **checksumming**, **compression**, and **deduplication**, all of which benefit from having a larger view of the data to be written.

---

## Benefits of Delayed Allocation

### Write Aggregation & Throughput

When a workload emits many small writes (e.g., a logging service writing 4 KB entries every few milliseconds), delayed allocation enables the filesystem to gather those writes into a larger **extent**—often 128 KB or more—before committing to disk.  The result is:

- Fewer I/O operations per second (IOPS) for the same amount of logical data.
- Higher **sequential write bandwidth**, because the drive’s internal command queue can be filled with larger, contiguous requests.
- Reduced CPU overhead for metadata handling (fewer bitmap updates, fewer journal entries).

### Reduced Fragmentation

Fragmentation hurts performance on spinning disks and can also degrade SSD wear‑leveling.  By allocating after the final size is known, the filesystem can:

- Place the file’s extents in a **single region** of free space.
- Align allocations to the device’s optimal **erase block size** (especially important for SSDs and NVMe with zoned namespaces).
- Avoid “write‑after‑write” patterns where a later write would have to split an existing extent.

### Improved SSD Longevity

SSDs have a limited number of program/erase cycles per block.  When writes are small and scattered, the SSD’s Flash Translation Layer (FTL) must perform **read‑modify‑write** cycles, accelerating wear.  Larger, sequential writes generated by delayed allocation:

- Allow the SSD to perform **full‑stripe writes**, minimizing write amplification.
- Enable the controller to perform **garbage collection** more efficiently.
- Reduce **write amplification factor (WAF)**, extending the device’s useful lifetime.

---

## Risks, Edge Cases, and Data‑Loss Scenarios

Delayed allocation is not a silver bullet.  The primary concern is **data loss on power failure or kernel panic** before the allocation occurs.  The following scenarios illustrate the risk:

| Scenario | What Happens | Mitigation |
|----------|--------------|------------|
| Application writes 1 MB, then exits without `fsync()` | Data resides only in page cache; if the system crashes before the write‑back timer fires, the data is lost. | Call `fsync()` or open the file with `O_SYNC`. |
| Filesystem mounted with `delalloc` on a device lacking a battery‑backed cache | The device’s volatile write cache may discard unflushed data on power loss, compounding the risk. | Use `sync` and `fsync`, or disable the device’s write cache (`hdparm -W0`). |
| Heavy write workload saturates memory, causing delayed allocation to be forced early | The kernel may allocate blocks earlier than ideal, reducing the benefit. | Increase `vm.dirty_background_ratio` and `vm.dirty_ratio` to give the cache more breathing room. |
| Database transaction commits but does not issue `fsync()` on its journal file | On crash, the journal may be incomplete, leading to corruption. | Use `fsync()` on the WAL (Write‑Ahead Log) files; many DBs provide configuration (`sync_binlog=1` in MySQL). |

> **Pro Tip**  
> For workloads that require **strong durability guarantees** (e.g., financial transaction logs), combine `delalloc` with **explicit `fsync()`** calls at logical commit points.  This keeps the performance benefits for bulk writes while ensuring safety for critical data.

---

## Tuning Delayed Allocation on Linux

### Mount Options

| Option | Description | Typical Use |
|--------|-------------|------------|
| `delalloc` (default) | Enables delayed allocation. | General purpose. |
| `nodalloc` | Disables delayed allocation. | Low‑latency workloads that cannot tolerate extra flush latency. |
| `data=ordered` | Guarantees that data is written before metadata. Works well with `delalloc`. | Default for ext4. |
| `data=writeback` | Allows metadata to be written before data; can increase risk of stale reads. | Rarely used, but may improve performance for temporary files. |
| `commit=SECONDS` | Forces the journal to commit every *SECONDS* (default 5). Adjusting this changes the window for delayed allocation. | Tuning for high‑throughput storage. |

Example mount command:

```bash
mount -t ext4 -o defaults,delalloc,commit=30 /dev/sdb1 /mnt/data
```

### sysctl Parameters

The kernel’s write‑back daemon is controlled by several `/proc/sys/vm/*` knobs:

```bash
# Proportion of memory that can be dirty before background writeback starts
sysctl -w vm.dirty_background_ratio=10

# Maximum proportion of dirty memory before processes are forced to write back
sysctl -w vm.dirty_ratio=20

# Minimum time (seconds) a dirty page can stay in memory before writeback
sysctl -w vm.dirty_writeback_centisecs=500   # 5 seconds

# Minimum time (seconds) before a dirty page is forced to sync (fsync)
sysctl -w vm.dirty_expire_centisecs=3000   # 30 seconds
```

Increasing `dirty_background_ratio` gives the page cache more room to coalesce writes, thereby **increasing the effectiveness of delayed allocation**.  However, set these values carefully on systems with limited RAM to avoid memory pressure.

### Application‑Level Strategies

1. **Batch Writes** – Instead of calling `write()` for each 4 KB record, aggregate them in user space (e.g., using a buffer) and write larger chunks (64 KB‑256 KB).  
2. **Explicit `fsync()` at Logical Boundaries** – For databases, issue `fsync()` after each transaction group rather than after every row insert.  
3. **Use `posix_fallocate()` for Pre‑allocation** – If you know the final size of a file (e.g., a video file), pre‑allocate with `posix_fallocate()` to avoid fragmentation while still benefiting from delayed allocation for the actual data.  

---

## Practical Examples

### Benchmarking Write Patterns with `dd`

The following script compares three scenarios on an ext4 filesystem mounted with `delalloc`:

```bash
#!/bin/bash
set -e

MOUNTPOINT=/mnt/delalloc_test
TESTFILE=$MOUNTPOINT/testfile

# 1. Small 4KB writes (no explicit fsync)
time dd if=/dev/urandom of=$TESTFILE bs=4K count=25000 conv=fdatasync

# 2. Large 256KB writes (no explicit fsync)
time dd if=/dev/urandom of=$TESTFILE bs=256K count=390 conv=fdatasync

# 3. Small writes with explicit fsync after each write
(
  exec 3> $TESTFILE
  for i in $(seq 1 25000); do
    head -c 4K </dev/urandom >&3
    sync
  done
) 2>/dev/null
```

**Expected outcome**:

- Scenario 1 will show higher CPU usage and longer runtime because the kernel must allocate blocks for each 4 KB write.
- Scenario 2 will be faster; the larger writes allow the kernel to allocate a single extent.
- Scenario 3 will be the slowest, demonstrating the cost of disabling delayed allocation via frequent `fsync()`.

### C Program Demonstrating `posix_fallocate` vs. Delayed Allocation

```c
#define _GNU_SOURCE
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#define FILESIZE (1024 * 1024 * 500)   // 500 MiB
#define CHUNK    (64 * 1024)          // 64 KiB

void die(const char *msg) {
    perror(msg);
    exit(EXIT_FAILURE);
}

/* Write data using delayed allocation (no pre‑allocation) */
void write_delalloc(const char *path) {
    int fd = open(path, O_CREAT | O_WRONLY | O_TRUNC, 0644);
    if (fd < 0) die("open");

    char *buf = malloc(CHUNK);
    if (!buf) die("malloc");
    memset(buf, 'A', CHUNK);

    size_t written = 0;
    while (written < FILESIZE) {
        ssize_t ret = write(fd, buf, CHUNK);
        if (ret < 0) die("write");
        written += ret;
    }

    /* Force metadata commit but keep data in cache */
    if (fsync(fd) < 0) die("fsync");
    close(fd);
    free(buf);
}

/* Write data after explicit pre‑allocation */
void write_prealloc(const char *path) {
    int fd = open(path, O_CREAT | O_WRONLY | O_TRUNC, 0644);
    if (fd < 0) die("open");

    if (posix_fallocate(fd, 0, FILESIZE) != 0) die("posix_fallocate");

    char *buf = malloc(CHUNK);
    if (!buf) die("malloc");
    memset(buf, 'B', CHUNK);

    size_t written = 0;
    while (written < FILESIZE) {
        ssize_t ret = write(fd, buf, CHUNK);
        if (ret < 0) die("write");
        written += ret;
    }
    if (fsync(fd) < 0) die("fsync");
    close(fd);
    free(buf);
}

int main(void) {
    const char *path1 = "delalloc.dat";
    const char *path2 = "prealloc.dat";

    printf("Writing with delayed allocation...\n");
    write_delalloc(path1);
    printf("Writing with pre‑allocation...\n");
    write_prealloc(path2);
    return 0;
}
```

**What to observe**:

- `posix_fallocate()` forces the filesystem to allocate the full 500 MiB up front, which can cause **fragmentation** if the free space is not contiguous.
- The delayed allocation version lets the kernel decide the best layout, often resulting in **fewer extents** and better performance on subsequent reads.

### Monitoring with `iostat` and `blktrace`

```bash
# Start monitoring
iostat -dx 1 /dev/sdb > iostat.log &
BLKTRACE_PID=$!

# Capture block-level traces for 30 seconds
blktrace -d /dev/sdb -o - | blkparse -i - > blktrace.log

# Stop iostat
kill $BLKTRACE_PID
```

Analyzing `blktrace.log` will reveal that, under delayed allocation, **large sequential I/O requests** dominate, while the non‑delayed scenario shows many small, scattered requests.  The `iostat` output will also display higher **%util** but fewer **await** times for the delayed case, confirming reduced latency per request.

---

## Real‑World Use Cases

### Databases (MySQL, PostgreSQL)

Both MySQL (InnoDB) and PostgreSQL use **write‑ahead logs (WAL)** that are flushed synchronously to guarantee durability.  However, the **data files** themselves can benefit from delayed allocation:

- **InnoDB** writes data pages to the buffer pool and only flushes them in groups, allowing ext4’s delayed allocation to allocate large extents for tablespaces.
- **PostgreSQL** employs a **checkpoint** mechanism that writes dirty buffers in bulk; the checkpoint interval (`checkpoint_timeout`) essentially sets the window for delayed allocation.

Tuning tip: set the database’s `innodb_flush_log_at_trx_commit=2` (MySQL) or `synchronous_commit = off` (PostgreSQL) for workloads where absolute durability per transaction is not required.  This reduces the number of forced `fsync()` calls, giving delayed allocation more time to aggregate writes.

### Virtual Machines & Containers

Hypervisors (KVM, VMware) store VM disks as large **qcow2** or **raw** files.  When many VMs write simultaneously, the host’s filesystem can become a bottleneck.  With delayed allocation:

- **qcow2** images often experience **write‑amplification** due to copy‑on‑write; however, delayed allocation reduces the number of allocation events, mitigating the amplification.
- Container storage drivers like **overlay2** create many small layers; using a host filesystem with `delalloc` helps keep the underlying `diff` directories from fragmenting.

### Log‑Heavy Applications

Systems such as **Kafka**, **Redis AOF**, or **web server access logs** generate high‑frequency, small writes.  Deploying them on a filesystem with delayed allocation (or explicitly configuring them to batch writes) can:

- Lower I/O latency during peak traffic.
- Reduce SSD wear, which is crucial for large log‑retention clusters.

---

## Comparing Delayed Allocation to Other Allocation Strategies

| Strategy | Allocation Time | Typical Write Size | Fragmentation | Metadata Overhead | Use‑Case |
|----------|----------------|--------------------|----------------|-------------------|----------|
| **Immediate Allocation** | On each `write()` | Small (4 KB) | High | High (bitmap update per write) | Real‑time systems needing deterministic latency. |
| **Pre‑allocation (`posix_fallocate`)** | At file creation or explicit call | Large (full file) | Low if space is contiguous | Medium (single bitmap reservation) | Media files, large databases. |
| **Delayed Allocation** | At flush (`fsync`, journal commit) | Variable (aggregated) | Low‑Medium (depends on flush frequency) | Low (single allocation per flush) | General‑purpose workloads, high‑throughput servers. |
| **Zoned Block Devices (ZBD) with Sequential Write Zones** | At zone‑boundary write | Large (zone size) | Very low (zone‑level) | Low (zone‑allocation tables) | Object storage, log‑structured systems. |

The table highlights that **delayed allocation** offers a sweet spot for most workloads: it balances safety (via journaling) with high performance, without requiring the application to know the final file size.

---

## Debugging & Troubleshooting

When you suspect delayed allocation is causing unexpected behavior, follow these steps:

1. **Verify Mount Options**  
   ```bash
   mount | grep $(df /path | tail -1 | awk '{print $1}')
   ```
   Ensure `delalloc` is listed.

2. **Check Dirty Page Statistics**  
   ```bash
   cat /proc/meminfo | grep -i dirty
   ```
   High `Dirty` values indicate that many pages are waiting to be flushed.

3. **Force a Flush and Observe Allocation**  
   ```bash
   sync && echo 3 > /proc/sys/vm/drop_caches
   ```
   After `sync`, examine the filesystem’s block usage with `dumpe2fs -h /dev/sdx1`.

4. **Use `fstrim` on SSDs** – If you notice a sudden rise in write amplification, run `fstrim` to discard unused blocks, then monitor again.

5. **Capture Kernel Logs**  
   ```bash
   dmesg | grep -i ext4
   ```
   Look for messages like “delayed allocation failed” which can indicate insufficient space or allocation timeout.

6. **Reproduce with `fsstress`**  
   The `fsstress` utility (part of `stress-ng`) can generate controlled workloads to test the impact of delayed allocation.

---

## Best Practices Checklist

- ✅ **Mount with `delalloc`** (default) on all production ext4/XFS partitions.  
- ✅ **Avoid frequent `fsync()`** on non‑critical data; batch syncs at logical checkpoints.  
- ✅ **Tune `vm.dirty_*`** values to give the page cache enough room for aggregation.  
- ✅ **Monitor I/O patterns** with `iostat`, `blktrace`, or `perf` to verify reduced fragmentation.  
- ✅ **Use `posix_fallocate`** only when the final file size is known and you need guaranteed space.  
- ✅ **Validate backup/restore procedures** to ensure that delayed‑allocation files are correctly captured (most backup tools read through the page cache, so no special handling is required).  
- ✅ **Test crash recovery** on a staging system: write data, power‑off, reboot, and verify integrity.  

---

## Future Directions and Emerging Trends

1. **Zoned Namespace (ZNS) SSDs** – These devices expose logical zones that must be written sequentially.  Filesystems like **F2FS** and **Linux’s zoned block driver** combine zone‑aware allocation with delayed allocation, providing even tighter control over write patterns.

2. **Persistent Memory (PMEM)** – With NVDIMM devices, the line between memory and storage blurs.  Projects such as **ext4’s “pmfs”** variant aim to keep allocation decisions in persistent RAM, potentially eliminating the need for delayed allocation entirely for certain workloads.

3. **Machine‑Learning‑Driven Allocation** – Research prototypes use workload profiling to predict optimal allocation windows, dynamically adjusting `commit` intervals and `dirty` thresholds based on real‑time analytics.

4. **User‑Space Filesystems (FUSE) with Delayed Allocation** – Modern distributed filesystems (e.g., **CephFS** and **GlusterFS**) expose tunable delayed allocation parameters via their client libraries, allowing per‑application control.

---

## Conclusion

Delayed allocation is a deceptively simple yet profoundly effective technique that transforms the way Linux filesystems handle writes. By postponing block reservation until the last responsible moment, it enables **write aggregation**, **dramatically reduces fragmentation**, and **extends the lifespan of flash storage**—all while preserving data integrity through journaling.

For administrators, the key takeaway is to **keep `delalloc` enabled**, tune the kernel’s dirty‑page thresholds, and design applications to **batch syncs** rather than flush after every tiny write.  For developers, understanding the interplay between `write()`, `fsync()`, and the filesystem’s allocation policy can guide the design of high‑performance I/O paths.

When employed wisely, delayed allocation becomes an invisible performance booster, delivering faster throughput and more resilient storage without requiring invasive code changes.  As storage technology evolves—particularly with zoned SSDs and persistent memory—delayed allocation will continue to adapt, remaining a cornerstone of modern file system design.

---

## Resources

- **The ext4 Delayed Allocation Design** – Official Linux kernel documentation  
  [https://www.kernel.org/doc/html/latest/filesystems/ext4/delayed-allocation.html](https://www.kernel.org/doc/html/latest/filesystems/ext4/delayed-allocation.html)

- **XFS Delayed Allocation Overview** – Red Hat Enterprise Linux documentation  
  [https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/monitoring_and_managing_the_system/chap-monitoring-and-managing-the-system-xfs](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/monitoring_and_managing_the_system/chap-monitoring-and-managing-the-system-xfs)

- **Understanding Linux VM Dirty Settings** – LWN.net article  
  [https://lwn.net/Articles/642119/](https://lwn.net/Articles/642119/)

- **Zoned Block Device Specification** – NVMe.org ZNS spec  
  [https://nvmexpress.org/wp-content/uploads/2020/04/Specifications-2.0.pdf](https://nvmexpress.org/wp-content/uploads/2020/04/Specifications-2.0.pdf)

- **"Write Amplification in SSDs: The Role of Filesystem Allocation Strategies"** – IEEE Transactions on Computers, 2023  
  [https://ieeexplore.ieee.org/document/10123456](https://ieeexplore.ieee.org/document/10123456)

- **MySQL 8.0 InnoDB Performance Tuning Guide** – Oracle Documentation  
  [https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html)

---