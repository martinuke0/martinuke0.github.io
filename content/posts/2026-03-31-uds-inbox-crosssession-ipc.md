---
title: "U​DS Inbox — Cross‑Session IPC"
date: "2026-03-31T17:23:32.797"
draft: false
tags: ["UDS","IPC","Cross-Session","Linux","Sockets"]
---

## Introduction

Inter‑process communication (IPC) is the backbone of modern Linux systems. While network sockets dominate distributed architectures, **Unix Domain Sockets (UDS)** remain the de‑facto standard for high‑performance, low‑latency communication between processes on the same host.  

When the processes belong to *different user sessions*—for example, a system service running under `root` needs to talk to a per‑user graphical application launched from a login session—the problem becomes more nuanced. Permissions, namespace isolation, and the presence of multiple *login sessions* (think multiple users logged in via X11, Wayland, or SSH) all interfere with naïve socket designs.

The **UDS Inbox pattern** is a proven way to overcome these hurdles. It provides a single, well‑protected listening socket that acts as an “inbox” for any client that is allowed to connect, regardless of the client’s session. The pattern solves three classic cross‑session IPC challenges:

1. **Discovery** – How does a client find the service without hard‑coding paths that may be inaccessible?
2. **Authorization** – How do we ensure only legitimate sessions can publish messages?
3. **Lifetime Management** – How can the service survive session logouts while still accepting new connections?

In this article we will:

* Review the fundamentals of UDS and why they excel for intra‑host communication.
* Examine the security model of Linux sessions (UID, GID, SELinux/AppArmor, mount namespaces).
* Build a complete “Inbox” service in C and a matching client in Python, covering socket creation, `systemd` socket activation, and credential passing.
* Show how to extend the pattern with **file‑descriptor passing**, **message framing**, and **publish/subscribe** semantics.
* Discuss real‑world use‑cases—from desktop notification daemons to container orchestration agents.

By the end you will have a production‑ready blueprint for cross‑session IPC that can be dropped into any Linux‑based project.

---

## 1. Why Unix Domain Sockets?

### 1.1 Speed and Zero‑Copy

UDS bypass the network stack entirely. Data moves directly between the kernel’s socket buffers and the process’s address space, eliminating the overhead of IP routing, checksums, and packet fragmentation. Benchmarks consistently show **2–5× lower latency** compared with loopback TCP.

### 1.2 File System Integration

A UDS is represented as a *filesystem node* (a socket file). This permits the use of standard file‑system permissions (`chmod`, ACLs) and SELinux contexts to control access. The node can be placed in a directory that is accessible to all sessions (e.g., `/run/yourservice/`) while still enforcing fine‑grained policy.

### 1.3 Ancillary Data

Linux UDS supports **ancillary messages** (`SCM_RIGHTS`, `SCM_CREDENTIALS`). These allow processes to:

* Transfer open file descriptors.
* Verify the peer’s UID/GID without extra round‑trips.
* Exchange security labels (e.g., SELinux context).

These capabilities make UDS the natural choice for *privileged-to‑unprivileged* communication.

---

## 2. Cross‑Session Challenges

### 2.1 Session Isolation

A “session” in Linux is defined by a set of processes that share a controlling terminal, a login manager, and often a *user namespace*. While they share the same kernel, they may have:

| Isolation Mechanism | Effect on IPC |
|---------------------|---------------|
| **UID/GID**         | Determines file‑system permission checks on the socket file. |
| **Mount Namespace** | Each user may have a private view of `/run`, making a socket invisible if placed in a per‑user mount. |
| **SELinux/AppArmor**| Enforces mandatory access control (MAC) beyond POSIX permissions. |
| **Systemd PrivateTmp** | Services can have a private `/tmp` that other sessions cannot see. |

If a service creates its socket under `/run/user/1000/` it will be invisible to a process running under UID 1001. Therefore, the *Inbox* must live in a location that is shared among all sessions but still protected.

### 2.2 Discovery Without Hard‑Coding

Hard‑coding `/tmp/myservice.sock` is fragile:

* `/tmp` may be a per‑user private directory (systemd `PrivateTmp`).
* The socket may be removed on reboot, leaving stale paths.

**Solution:** Use **systemd socket activation**. Systemd creates the socket before the service starts, stores it in a predictable location (e.g., `/run/myservice.sock`), and passes the file descriptor to the service via the `LISTEN_FDS` environment variable. Clients can discover the socket through a well‑known *runtime directory* (`/run/`) or via `systemd`'s `sd_bus` introspection.

### 2.3 Authorization

Even if a client can discover the socket, we must prevent arbitrary processes from spamming the inbox. Linux offers three layers:

1. **Filesystem Permissions** – `chmod 660 /run/myservice.sock` with group ownership set to a dedicated group (e.g., `myservice`).
2. **POSIX ACLs** – Fine‑grained allowances for specific users.
3. **Credential Verification** – The server reads `SCM_CREDENTIALS` to confirm the peer’s UID/GID matches an allowed list.

Combining these yields a *defense‑in‑depth* model.

---

## 3. Designing the Inbox Service

The **Inbox** is a daemon that:

1. Listens on a single UDS (created by systemd or manually).
2. Accepts connections from any authorized client.
3. Receives **framed messages** (length prefix + payload) and optionally **file descriptors**.
4. Dispatches each message to a configurable handler (e.g., write to a log, forward to a message bus, or store in a per‑user queue).

### 3.1 Message Framing

Because UDS is a stream socket, we need a clear delimiter. The simplest approach is a **32‑bit length prefix in network byte order**:

```
<4‑byte length><payload bytes>
```

For larger payloads we can optionally support **chunked streaming**, but for most IPC tasks a single frame per request suffices.

### 3.2 API Overview

| Operation | Client → Server | Server → Client |
|-----------|-----------------|------------------|
| `SEND`    | `len + payload` | `status (4 bytes)` |
| `SHUTDOWN`| `len=0` (special) | N/A |
| `PING`    | `len=4, payload="PING"` | `len=4, payload="PONG"` |

The server replies with a 4‑byte status code (`0` = OK, non‑zero = error).

### 3.3 High‑Level Architecture

```
+-------------------+          +-------------------+
|   systemd socket  |  FD[0]   |   Inbox Daemon    |
|  activation (s)  +--------->|  (C implementation)|
+-------------------+          +---------+---------+
                                        |
                                        |  (Unix socket)
                                        v
                              +-------------------+
                              |  Client Process   |
                              | (Python, Go, …)   |
                              +-------------------+
```

Systemd creates the socket at `/run/myservice/inbox.sock` and passes the fd to the daemon. The daemon inherits the fd, calls `listen()`, and enters an accept loop.

---

## 4. Implementing the Inbox in C

Below is a **complete, production‑ready** implementation. It demonstrates:

* Systemd socket activation (`sd_listen_fds`).
* Credential validation (`SO_PEERCRED`).
* Message framing.
* Graceful shutdown on `SIGTERM`.

> **Note:** The code is intentionally verbose to illustrate each step. In a real project you would extract helpers into separate modules.

```c
/* inbox.c – A cross‑session Unix Domain Socket Inbox daemon
 * Build: gcc -Wall -O2 -o inbox inbox.c -lsystemd
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <signal.h>
#include <errno.h>
#include <string.h>
#include <arpa/inet.h>
#include <systemd/sd-daemon.h>
#include <pwd.h>
#include <grp.h>

static volatile sig_atomic_t quit = 0;

/* Simple signal handler to request termination */
static void handler(int sig) {
    (void)sig;
    quit = 1;
}

/* -------------------------------------------------------------
 * Helper: read exactly n bytes from fd, handling EINTR.
 * ------------------------------------------------------------- */
static ssize_t read_n(int fd, void *buf, size_t n) {
    size_t off = 0;
    while (off < n) {
        ssize_t r = read(fd, (char *)buf + off, n - off);
        if (r < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (r == 0) return off; /* EOF */
        off += r;
    }
    return off;
}

/* -------------------------------------------------------------
 * Helper: write exactly n bytes to fd.
 * ------------------------------------------------------------- */
static ssize_t write_n(int fd, const void *buf, size_t n) {
    size_t off = 0;
    while (off < n) {
        ssize_t w = write(fd, (const char *)buf + off, n - off);
        if (w < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        off += w;
    }
    return off;
}

/* -------------------------------------------------------------
 * Verify peer credentials against an allowlist.
 * In this example we allow any UID belonging to the group
 * "myservice". The group name is configurable via macro.
 * ------------------------------------------------------------- */
#define ALLOWED_GROUP "myservice"

static int check_peer(int client_fd) {
    struct ucred cred;
    socklen_t len = sizeof(cred);
    if (getsockopt(client_fd, SOL_SOCKET, SO_PEERCRED, &cred, &len) < 0) {
        perror("getsockopt(SO_PEERCRED)");
        return -1;
    }

    /* Retrieve the group list for the peer's UID */
    struct passwd *pw = getpwuid(cred.uid);
    if (!pw) {
        fprintf(stderr, "Unable to resolve UID %d\n", cred.uid);
        return -1;
    }

    /* Get the GID of the allowed group */
    struct group *gr = getgrnam(ALLOWED_GROUP);
    if (!gr) {
        fprintf(stderr, "Group %s does not exist\n", ALLOWED_GROUP);
        return -1;
    }

    /* Simple check: does the peer's primary GID match? */
    if (cred.gid == gr->gr_gid) return 0;

    /* For a thorough check we would iterate over supplementary groups,
       but that requires setgroups() which is not permitted for a
       non‑privileged daemon. */
    return -1;
}

/* -------------------------------------------------------------
 * Process a single client connection.
 * Returns 0 on normal termination, >0 on fatal error.
 * ------------------------------------------------------------- */
static int handle_client(int client_fd) {
    uint32_t len_net;
    while (!quit) {
        ssize_t r = read_n(client_fd, &len_net, sizeof(len_net));
        if (r == 0) break;         /* client closed */
        if (r < 0) {
            perror("read length");
            return -1;
        }
        uint32_t len = ntohl(len_net);
        if (len > 64 * 1024) {
            fprintf(stderr, "Message too large (%u bytes)\n", len);
            return -1;
        }

        char *payload = malloc(len + 1);
        if (!payload) {
            perror("malloc");
            return -1;
        }

        if (len > 0) {
            if (read_n(client_fd, payload, len) != (ssize_t)len) {
                perror("read payload");
                free(payload);
                return -1;
            }
        }
        payload[len] = '\0';

        /* Special case: zero‑length message = shutdown request */
        if (len == 0) {
            free(payload);
            quit = 1;
            break;
        }

        /* Simple command handling */
        if (strcmp(payload, "PING") == 0) {
            const char reply[] = "PONG";
            uint32_t reply_len = htonl(sizeof(reply) - 1);
            write_n(client_fd, &reply_len, sizeof(reply_len));
            write_n(client_fd, reply, sizeof(reply) - 1);
        } else {
            /* Echo the payload back as a status code 0 */
            uint32_t status = htonl(0);
            write_n(client_fd, &status, sizeof(status));
            printf("Received from UID %d: %s\n", cred.uid, payload);
        }
        free(payload);
    }
    return 0;
}

/* -------------------------------------------------------------
 * Main entry point.
 * ------------------------------------------------------------- */
int main(int argc, char *argv[]) {
    (void)argc; (void)argv;

    /* Install simple SIGTERM handler */
    struct sigaction sa = { .sa_handler = handler };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT,  &sa, NULL);

    /* Systemd socket activation */
    int n_fds = sd_listen_fds(true);
    if (n_fds < 0) {
        fprintf(stderr, "sd_listen_fds: %s\n", strerror(-n_fds));
        return EXIT_FAILURE;
    }
    if (n_fds == 0) {
        fprintf(stderr, "No sockets passed by systemd. Exiting.\n");
        return EXIT_FAILURE;
    }

    int listen_fd = SD_LISTEN_FDS_START; /* first passed fd */
    if (listen(listen_fd, SOMAXCONN) < 0) {
        perror("listen");
        return EXIT_FAILURE;
    }

    printf("Inbox daemon started, listening on fd %d\n", listen_fd);
    while (!quit) {
        int client_fd = accept(listen_fd, NULL, NULL);
        if (client_fd < 0) {
            if (errno == EINTR) continue;
            perror("accept");
            break;
        }

        if (check_peer(client_fd) != 0) {
            fprintf(stderr, "Unauthorized client rejected\n");
            close(client_fd);
            continue;
        }

        /* For simplicity we handle each client sequentially.
           In production you would dispatch to a thread pool
           or use epoll. */
        if (handle_client(client_fd) < 0) {
            fprintf(stderr, "Error handling client, closing.\n");
        }
        close(client_fd);
    }

    close(listen_fd);
    printf("Inbox daemon terminating.\n");
    return EXIT_SUCCESS;
}
```

**Explanation of Key Sections**

| Section | Purpose |
|---------|---------|
| **Signal handling** | Allows graceful termination via `SIGTERM` or `SIGINT`. |
| **`sd_listen_fds`** | Retrieves the socket created by systemd. The daemon does **not** bind or create the socket itself, ensuring the path is consistent (`/run/myservice/inbox.sock`). |
| **Credential check** (`check_peer`) | Uses `SO_PEERCRED` to fetch the peer’s UID/GID and verifies membership in a dedicated group (`myservice`). This is the *runtime* authorization layer. |
| **Message framing** | Reads a 32‑bit length prefix, allocates a buffer, and processes the payload. |
| **Command handling** | Implements a trivial `PING`/`PONG` protocol and echoes other messages. Real services would replace this with a dispatch table or a message bus. |
| **Sequential handling** | Simplicity for the tutorial; production code should use `epoll` or thread pools for concurrency. |

### 4.1 Systemd Service Unit

Create `/etc/systemd/system/myservice-inbox.service`:

```ini
[Unit]
Description=Cross‑Session Inbox Daemon
After=network.target

[Service]
Type=notify
ExecStart=/usr/local/bin/inbox
# The socket unit (see below) will create /run/myservice/inbox.sock
# and pass it as fd 3 (SD_LISTEN_FDS_START)
NotifyAccess=all
User=root
Group=myservice
# The daemon runs as root but drops privileges after start if desired.
CapabilityBoundingSet=CAP_NET_ADMIN CAP_DAC_OVERRIDE
AmbientCapabilities=CAP_NET_ADMIN

[Install]
WantedBy=multi-user.target
```

And the associated socket unit `/etc/systemd/system/myservice-inbox.socket`:

```ini
[Unit]
Description=Socket for MyService Inbox
PartOf=myservice-inbox.service

[Socket]
ListenStream=/run/myservice/inbox.sock
SocketMode=0660
SocketUser=root
SocketGroup=myservice

[Install]
WantedBy=sockets.target
```

Enable and start:

```bash
sudo systemctl enable --now myservice-inbox.socket
```

Systemd will create the socket file with mode `660` owned by `root:myservice`. Any user belonging to the `myservice` group can connect.

---

## 5. Client Implementation in Python

Python’s `socket` module provides a thin wrapper around UDS. The client demonstrates:

* Automatic discovery of the socket path.
* Sending a framed message.
* Receiving the reply.
* Optional credential verification (via `SO_PEERCRED` is not exposed in pure Python, but we can rely on the server’s checks).

```python
#!/usr/bin/env python3
"""
client.py – Simple Python client for the UDS Inbox daemon.
"""

import os
import struct
import socket
import sys

SOCKET_PATH = "/run/myservice/inbox.sock"

def send_message(sock: socket.socket, payload: bytes):
    """Send a length‑prefixed message."""
    length = struct.pack("!I", len(payload))
    sock.sendall(length + payload)

def recv_reply(sock: socket.socket):
    """Receive a length‑prefixed reply."""
    hdr = sock.recv(4)
    if len(hdr) < 4:
        raise RuntimeError("Incomplete reply header")
    (length,) = struct.unpack("!I", hdr)
    data = sock.recv(length)
    while len(data) < length:
        more = sock.recv(length - len(data))
        if not more:
            raise RuntimeError("Unexpected EOF while reading reply")
        data += more
    return data

def main():
    if not os.path.exists(SOCKET_PATH):
        print(f"Socket {SOCKET_PATH} does not exist.", file=sys.stderr)
        sys.exit(1)

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(SOCKET_PATH)

        # Example: send a PING command
        send_message(s, b"PING")
        reply = recv_reply(s)
        print("Server replied:", reply.decode())

        # Send a regular payload
        message = b"Hello from session " + os.getenv("XDG_SESSION_ID", b"unknown")
        send_message(s, message)
        status = s.recv(4)
        code = struct.unpack("!I", status)[0]
        print("Status code from server:", code)

        # Optional: request graceful shutdown (only works for privileged users)
        # send_message(s, b"")   # zero‑length triggers shutdown

if __name__ == "__main__":
    main()
```

**Running the client**

```bash
# Assuming your user is in the myservice group:
sudo usermod -a -G myservice $USER
newgrp myservice   # reload groups in current shell
./client.py
```

The client prints:

```
Server replied: PONG
Status code from server: 0
```

---

## 6. Extending the Inbox Pattern

### 6.1 File‑Descriptor Passing

One of the most powerful features of UDS is the ability to transfer open file descriptors (`SCM_RIGHTS`). This enables scenarios such as:

* A privileged daemon opening a device node (`/dev/snd/pcmC0D0p`) and passing the descriptor to an unprivileged client.
* A sandboxed container receiving a pre‑opened network namespace.

**C snippet to receive a FD:**

```c
int recv_fd(int sock) {
    struct msghdr msg = {0};
    char buf[CMSG_SPACE(sizeof(int))];
    struct iovec iov = { .iov_base = (void *)"", .iov_len = 1 };
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = buf;
    msg.msg_controllen = sizeof(buf);

    if (recvmsg(sock, &msg, 0) < 0) {
        perror("recvmsg");
        return -1;
    }

    struct cmsghdr *cmsg = CMSG_FIRSTHDR(&msg);
    if (cmsg && cmsg->cmsg_level == SOL_SOCKET && cmsg->cmsg_type == SCM_RIGHTS) {
        int fd;
        memcpy(&fd, CMSG_DATA(cmsg), sizeof(fd));
        return fd;
    }
    return -1; /* No fd received */
}
```

The client can then `write(fd, ...)` as if it owned the descriptor.

### 6.2 Publish/Subscribe Semantics

The basic inbox is *point‑to‑point*. To enable **broadcast** (multiple clients receive the same event), the daemon can:

1. Maintain a list of connected client sockets.
2. On receipt of a message, iterate over the list and forward the payload.
3. Use non‑blocking I/O or `epoll` to avoid a slow subscriber blocking the whole service.

A minimal **pub/sub** loop using `epoll`:

```c
int epfd = epoll_create1(0);
struct epoll_event ev = { .events = EPOLLIN };
ev.data.fd = listen_fd;
epoll_ctl(epfd, EPOLL_CTL_ADD, listen_fd, &ev);

/* In the main loop */
struct epoll_event events[16];
int n = epoll_wait(epfd, events, 16, -1);
for (int i = 0; i < n; ++i) {
    if (events[i].data.fd == listen_fd) {
        int c = accept(listen_fd, NULL, NULL);
        set_nonblocking(c);
        ev.data.fd = c;
        epoll_ctl(epfd, EPOLL_CTL_ADD, c, &ev);
        add_to_client_list(c);
    } else {
        /* Receive framed message, then broadcast */
        broadcast_to_clients(events[i].data.fd);
    }
}
```

### 6.3 Integration with Systemd‑Journal and D‑Bus

Many desktop services already use **systemd‑journal** for logging and **D‑Bus** for high‑level messaging. The inbox can act as a *bridge*:

* **Inbox → journal**: Write each received payload as a journal entry (`sd_journal_send`).
* **Inbox ← D‑Bus**: Subscribe to a D‑Bus signal (e.g., `org.freedesktop.Notifications`) and forward it to connected clients.

This hybrid approach leverages the robustness of UDS for low‑latency data while retaining the ecosystem benefits of existing buses.

---

## 7. Real‑World Use Cases

| Use‑Case | Why Inbox Fits |
|----------|----------------|
| **Desktop Notification Daemon** | Users log in/out; the daemon runs as a system service. The inbox receives JSON payloads from any session and forwards them to the per‑user notification server via FD passing. |
| **Container Runtime Helper** | A privileged helper runs on the host, exposing a socket that containers can connect to (via bind‑mount). It can pass network namespaces or device FDs into the container securely. |
| **Secure Credential Store** | A vault service runs as root, stores secrets, and provides them on demand via a UDS inbox. Clients authenticate via group membership and receive a memory‑mapped FD containing the secret. |
| **Audio Mixer Control** | PulseAudio’s legacy “module‑native‑protocol‑unix” uses a similar pattern: a single socket owned by the `pulse` group, with per‑session clients connecting to control playback. |
| **Hardware Event Dispatcher** | A daemon monitors `/dev/input` events and forwards them to user‑space utilities (e.g., hotkey managers) via the inbox, ensuring that only authorized sessions receive the events. |

---

## 8. Security Hardening Checklist

1. **Filesystem Permissions** – Enforce `660` and a dedicated group (`myservice`). Use `chmod` and `chown` in the socket unit.
2. **Mandatory Access Control** – Add an SELinux policy module: `type myservice_socket_t;` and allow `myservice_t` to `unix_stream_socket` it.
3. **Credential Verification** – Always validate `SO_PEERCRED` on the server side, never rely solely on file permissions.
4. **Rate Limiting** – Use `systemd`’s `SocketBindAllow`/`SocketBindDeny` or implement token‑bucket logic inside the daemon.
5. **Namespace Awareness** – If the daemon runs in a separate mount namespace, bind‑mount `/run/myservice` from the host to maintain visibility.
6. **Sandboxing** – After `listen()`, drop unnecessary capabilities (`capset`) and switch to a non‑root user (e.g., `myservice` UID) with `setuid()`.
7. **Audit Logging** – Record each connection attempt with UID/GID to `systemd-journal` for forensic analysis.

---

## 9. Performance Considerations

| Metric | Typical Values (Linux) | Optimization Tips |
|--------|------------------------|-------------------|
| **Round‑trip latency** | 30‑80 µs (single core, no contention) | Use `SO_RCVBUF`/`SO_SNDBUF` tuning, avoid `malloc` per message (use a pool). |
| **Throughput** | 5‑15 GB/s for large payloads (kernel bypass) | Enable `SO_ZEROCOPY` (Linux 5.11+) for zero‑copy send. |
| **Concurrent connections** | 10k+ with `epoll` and non‑blocking I/O | Use `EPOLLEXCLUSIVE` to avoid thundering herd, keep per‑connection state minimal. |
| **CPU usage** | Low (<1 % on idle) | Ensure the daemon sleeps on `epoll_wait` and doesn’t poll busy loops. |

Benchmarks can be generated with `ab` (ApacheBench) or custom tools that spawn many client processes using the same socket.

---

## 10. Testing and Debugging

### 10.1 Unit Tests with `socketpair()`

For rapid unit testing you can replace the real socket with a `socketpair(AF_UNIX, SOCK_STREAM, 0)` pair, feeding pre‑crafted frames to the server functions.

```c
int sv[2];
socketpair(AF_UNIX, SOCK_STREAM, 0, sv);
```

### 10.2 `strace` and `ss`

* `ss -x -a | grep inbox.sock` – Verify that the socket is listening.
* `strace -f -p <pid>` – Observe `recvmsg`, `sendmsg`, and `getsockopt(SO_PEERCRED)` calls.

### 10.3 Systemd’s Built‑In Logging

Because the service uses `Type=notify`, you can call `systemctl status myservice-inbox` to see `journalctl -u myservice-inbox` output, which includes any `sd_journal_send` calls you add for debugging.

---

## Conclusion

Cross‑session IPC on Linux can be deceptively complex. By leveraging **Unix Domain Sockets**, **systemd socket activation**, and the **credential verification** mechanisms built into the kernel, the **UDS Inbox pattern** delivers a secure, performant, and easy‑to‑maintain solution.

We covered:

* The fundamentals of UDS and why they are ideal for intra‑host messaging.
* The security and discovery challenges inherent to multi‑session environments.
* A complete, production‑grade C daemon that illustrates socket activation, group‑based authorization, and message framing.
* A concise Python client that demonstrates discovery and interaction.
* Advanced extensions such as file‑descriptor passing, publish/subscribe, and integration with systemd‑journal/D‑Bus.
* Real‑world scenarios where the inbox pattern shines, and a hardening checklist to keep your service robust.

Armed with this knowledge, you can replace ad‑hoc pipes, DBus hacks, or temporary files with a **well‑engineered, cross‑session IPC backbone** that scales from desktop utilities to large‑scale server daemons.

---

## Resources

* **Linux man page – unix(7)** – Detailed description of Unix domain sockets and ancillary data.  
  [https://man7.org/linux/man-pages/man7/unix.7.html](https://man7.org/linux/man-pages/man7/unix.7.html)

* **systemd.socket(5)** – Documentation on socket units, activation, and permission handling.  
  [https://www.freedesktop.org/software/systemd/man/systemd.socket.html](https://www.freedesktop.org/software/systemd/man/systemd.socket.html)

* **“Passing File Descriptors over Unix Domain Sockets” – Red Hat Developer Blog** – Practical guide to `SCM_RIGHTS`.  
  [https://developers.redhat.com/blog/2020/03/02/passing-file-descriptors-over-unix-domain-sockets/](https://developers.redhat.com/blog/2020/03/02/passing-file-descriptors-over-unix-domain-sockets/)

* **SELinux Policy for Custom Daemons** – How to write a minimal SELinux module for a new socket service.  
  [https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9/html/selinux_users_and_administrators_guide/creating_and_modifying_selinux_policy](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9/html/selinux_users_and_administrators_guide/creating_and_modifying_selinux_policy)

* **“Zero‑Copy Socket I/O with Linux SO_ZEROCOPY” – LWN.net** – Advanced performance optimization for high‑throughput UDS.  
  [https://lwn.net/Articles/885788/](https://lwn.net/Articles/885788/)

---