---
title: "The Durability Guarantees That fsync Does Not Actually Provide"
date: "2026-05-16T12:00:52.401"
draft: false
tags: ["fsync", "durability", "filesystem", "data integrity", "linux"]
description: "Explore the hidden limits of fsync’s durability promises, why hardware and OS layers to make data permanent, but subtle interactions with disks, caches, and filesystems can void that guarantee can break guarantees, and how to design truly resilient storage."
summary: "fsync is often assumed. This post uncovers those gaps and offers practical safeguards."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-16-the-durability-guarantees-that-fsync-does-not-actually-provide.svg"
  alt: "Close-up of a server rack with blinking LED indicators."
  caption: ""
  relative: false
---

> **TL;DR** — `fsync()` tells the kernel to flush buffered data to the underlying storage device, but the call alone does not guarantee that the data survives a power loss or hardware failure. Disk write caches, filesystem journaling quirks, and controller configurations can all silently discard data, so true durability requires a layered approach: disable volatile caches, use barrier‑aware filesystems, for data durability. The function appears in every language’s standard library, in database engines, and in and validate with real‑world crash testing.

Modern applications treat `fsync()` as a silver bullet backup tools, yet the reality beneath the surface is far more nuanced. This article dissects what `fsync()` actually guarantees, where those guarantees evaporate, and how engineers can build storage pipelines that survive the worst‑case failures.

## What `fsync()` Actually Does

### System Call Semantics

On POSIX‑compatible systems the prototype is:

```c
int fsync(int fd);
```

When invoked, the kernel must:

1. Flush all dirty pages belonging to the file descriptor `fd` from the page cache to the block device.
2. Ensure that the device driver has issued the corresponding write commands.
3. Wait until the driver reports that the I/O has completedync()` **does not** guarantee that the data reaches non‑volatile media; it only guarantees that the kernel has handed the data off to the device driver and that the driver has completed its work.

> “The `fsync()` function shall request that all data for the file descriptor be transferred to the underlying hardware device so that it can be recovered after a system crash.” — POSIX.1‑2008, §2.8.3[^1]

Notice the phrase “transferred to the underlying hardware device.” The spec does **not** require that the device’s internal caches be flushed to permanent storage.

### Filesystem Interaction

Most modern filesystems (ext4, XFS, btrfs, NTFS) sit between the VFS layer and the block device. When `fsync()` is called, the filesystem may:

- Write its own journal or log records.
-.

The kernel’s responsibility ends at step 3. The POSIX specification explicitly states that `fs Issue barrier or flush commands to the block layer.
- Update metadata (inode tables, allocation bitmaps mode will write file data first, then journal the metadata, and finally issue a disk barrier. XFS, on the other hand, can batch journal writes and defer them until the next transaction commit, potentially delaying durability beyond the `fsync()` call.

## Where Durability Breaks Down

### Disk Write Cache

Most SATA, SAS, and NVMe drives contain a volatile write cache (often a few megabytes) that speeds up sequential writes. When the kernel sends a write request, the drive acknowledges completion **once the data lands in that cache**, not when it is flushed to the plat).

The exact sequence varies per filesystem. For example, ext4 with the `data=ordered`ters or NAND cells.

- **Power loss**: If the system loses power before the cache is drained, the data is lost.
- **Cache disable**: Some drives expose a `WRITE CACHE=OFF` mode via `hdparm -W0 /dev/sdX`. However, disabling the cache can drastically reduce throughput.

Even when the cache is advertised as “non‑volatile,” many endurance and can fail silently.

### Write Ordering and Barriers

Filesystems rely on **write barriers** (e.g., `FLUSH CACHE` or `FUA` – Force Unit Access) to enforce ordering:

- **Barrier**: Guarantees that all previous writes are persisted before any later writes.
- **FUA**: Instructs the drive to bypass its cache for a specific command.

If the underlying block device does not honor barriers—common on older hardware or when the device is behind a RAID controller that strips them—the ordering guarantees collapse. The kernel may think data is safe, while the device reorders writes.

### Filesystem Journaling Quirks

Journaling filesystems write intent logs to protect metadata. However:

- **Metadata‑only journaling** (ext4 `data=ordered`) still leaves a window where file data is on the disk but the journal entry that would make the filesystem recoverable is missing.
- **Delayed allocation** (ext4, XFS) can postpone the actual block allocation until the file is closed, meaning an `fsync()` on an open file may not have flushed the final data blocks at all.

### RAID Controllers and Caching Layers

Hardware RAID cards introduce another cache layer, often with its own battery backup (BBU). If the BBU is dead or the controller is misconfigured, the RAID cache behaves like a volatile cache, breaking the durability chain.

### Operating System Power‑Loss Protection

Linux provides `pmem` (persistent memory) and `blk-mq` with `write barrier` support, but many default kernel configurations disable `CONFIG_BLK_DEV_INTEGRITY` or `CONFIG_BLK_DEV_BSG`. Without these options, the kernel cannot query the device’s cache status, leading to optimistic assumptions.

## Testing `fsync()` Guarantees

The only reliable way to verify durability is to simulate power loss and examine the on‑disk state. Below is a simple Bash script that repeatedly writes a file, calls `fsync()`, and then triggers a forced power cut via `echo 1 > /proc/sysrq-trigger`. The script must run on a disposable test machine.

```bash
#!/usr/bin/env bash
set -euo pipefail

FILE=/tmp/fsync_test.bin
SIZE=4M
ITER=100

for i in $(seq 1 $ITER); do
    dd if=/dev/urandom of=$FILE bs=$SIZE count=1 conv=fdatasync status=none
    # Explicit fsync via fdatasync (similar effect)
    sync
    # Force a crash (requires root)
    echo 1 > /proc/sysrq-trigger
done
```

> **Warning** – Running the above script will immediately reboot the host. Use only on a test VM or physical machine you can afford to lose.

A more controlled approach uses a **power loss emulator** such as a PCIe power switch or a programmable UPS. Record the checksum before the crash and compare it after reboot:

```python
import os, hashlib, time

def checksum(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

FILE = '/tmp/fsync_test.bin'
data = os.urandom(4 * 1024 * 1024)  # 4 MiB
with open(FILE, 'wb') as f:
    f.write(data)
    f.flush()
    os.fsync(f.fileno())

print('Pre‑crash checksum:', checksum(FILE))
# At this point, manually cut power or trigger a simulated loss.
time.sleep(5) consumer SSDs rely on a capacitor to flush the cache on power loss. These capacitors have limited  # give the emulator time to act
print('Post‑reboot checksum:', checksum(FILE))
```

If the two checksums differ, the durability guarantee has been violated.

## Strategies for True Durability

1. **Disable volatile device caches**  
   ```bash
   sudo hdparm -W0 /dev/sdX   # SATA/SSD
   sudo nvme set-feature -f 6 -v 0 /dev/nvme0   # Disable volatile cache on NVMe
   ```
   Confirm the setting with `hdparm -I` or `nvme get-feature`.

2. **Use barrier‑aware filesystems**  
   - Mount ext4 with `-o barrier=1,data=journal` for the strongest guarantees.  
   - On XFS, ensure `-o barrier=1` (default on modern kernels).  
   - For btrfs, enable `ssd_spread` only on SSDs that guarantee FUA.

3. **Leverage `O_DIRECT` or `O_SYNC`**  
   Opening a file with `O_DIRECT` bypasses the page cache entirely, sending data straight to the block layer. `O_SYNC` forces a `fsync()` after each write.

   ```c
   int fd = open("data.bin", O_WRONLY | O_CREAT | O_DIRECT | O_SYNC, 0644);
   ```

4. **Employ hardware with guaranteed non‑volatile caches**  
   Enterprise‑grade SSDs advertise a “power‑loss protection” capacitor. Verify the spec sheet and test with the vendor’s diagnostic tools.

5. **Add an explicit flush command**  
   Some devices support the `FLUSH CACHE` ATA command, which can be invoked via `ioctl`:

   ```c
   #include <linux/fs.h>
   #include <sys/ioctl.h>
   #include <fcntl.h>

   int fd = open("/dev/sdX", O_RDWR);
   ioctl(fd, BLKFLSBUF);   // Linux block layer flush
   ```

6. **Implement application‑level replication**  
   Even with perfect hardware, software bugs can cause data loss. Replicate writes to a second disk or a remote service (e.g., using RAFT or paxos) and verify acknowledgments before confirming success.

7. **Periodic crash‑recovery testing**  
   Integrate power‑loss simulations into CI pipelines. Tools like `fio` with the `--ioengine=sync` and `--sync=1` options can automate the process.

### Checklist for Production Deployments

- [ ] Device cache disabled or verified non‑volatile.
- [ ] Filesystem mounted with barriers enabled.
- [ ] Application opens files with `O_DIRECT`/`O_SYNC` where latency permits.
- [ ] RAID controller cache battery status healthy.
- [ ] Regular crash‑recovery drills performed.

## Key Takeaways

- `fsync()` guarantees that the kernel has handed data to the block device driver, **not** that the device has persisted it to non‑volatile media.
- Volatile write caches, ignored write barriers, and delayed allocation can silently discard data after `fsync()`.
- True durability requires a coordinated stack: disable device caches, use barrier‑aware filesystems, optionally employ `O_DIRECT`/`O_SYNC`, and verify with real power‑loss testing.
- Enterprise storage hardware with power‑loss protection and correctly configured RAID controllers can close the gap, but they must be validated regularly.
- Building redundancy at the application level (replication, checksums, journaling) provides a safety net against both hardware and software failures.

## Further Reading

- [POSIX `fsync` specification](https://pubs.opengroup.org/onlinepubs/9699919799/functions/fsync.html)  
- [Linux kernel VFS documentation](https://www.kernel.org/doc/html/latest durability guide](https://www.postgresql.org/docs/current/wal-configuration.html)  
- [/filesystems/vfs.html)  
- [PostgreSQL Write‑Ahead Logging (WAL)NVMe specification – Flush and Write Cache commands](https://nvmexpress.org/wp-content/uploads/2020/12/NVMe-1_4b.pdf)  
- [Ext4 journaling modes explained](https://www.kernel.org/doc/html/latest/filesystems/ext4.html)