---
title: "Implementing Fine-Grained Seccomp BPF Filters for Container Isolation"
date: "2026-10-29T23:00:58.452"
draft: false
tags: ["container-security", "seccomp", "linux", "container-isolation", "kubernetes"]
description: "Learn how to implement fine-grained seccomp BPF filters to harden container isolation, reduce attack surface, and productionize secure deployments."
summary: "A practical guide to building and deploying fine-grained seccomp BPF profiles for containerized workloads, with real-world patterns and BPF compiler tools."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-29-implementing-fine-grained-seccomp-bpf-filters-for-container-isolation.svg"
  alt: "Diagram of seccomp BPF filter rules isolating container system calls"
  caption: ""
  relative: false
---

> **TL;DR** — Seccomp BPF filters let you whitelist only the system calls your container actually needs, slashing the attack surface by 70–90% in production workloads. By building profiles with tools like bpffs or Docker’s seccomp profile compiler, you can harden isolation without sacrificing functionality, and enforce them declaratively in Kubernetes or containerd.

## Introduction
Container security is often reduced to `run as non-root` and `drop all capabilities`, but the kernel system call interface remains a broad attack surface. Every syscall a container can make is a potential exploit path—from `openat` and `unlink` to more subtle vectors like `futex` races or `ptrace`. Seccomp BPF (Berkeley Packet Filter) provides a mechanism to restrict that interface to a minimal, verified set. Fine-grained filters go beyond the default whitelist, surgically removing unnecessary calls and even emulating or blocking specific dangerous ones.

In this post, we’ll walk through how to design, build, and deploy fine-grained seccomp BPF filters for containerized workloads, with concrete patterns for Kubernetes, Docker, and containerd, and anti-patterns to avoid. We’ll cover the BPF model, profile construction, runtime integration, debugging techniques, and real-world profile examples you can adapt today.

## The Seccomp BPF Model
### BPF Bytecode Basics
At its core, seccomp BPF filters are programs written in BPF bytecode that the kernel executes for each system call a process makes. The program returns one of three outcomes:
- `SECCOMP_RET_ALLOW` (value 0x7fff0000) — permit the syscall
- `SECCOMP_RET_KILL` (value 0x00000000) — immediately kill the process with `SIGKILL`
- `SECCOMP_RET_TRAP` (value 0x00050000) — deliver `SIGSYS` to the process, allowing it to handle the violation

A filter is attached to a thread via `prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &prog)`. Once active, every syscall entering that thread passes through the filter. If the filter does not explicitly allow a call, it is denied.

The BPF verifier ensures program safety: it must terminate, not diverge, and operate within strict instruction limits (currently 4,094 instructions on most kernels). This verifier is why we use high-level tools to generate BPF rather than hand-writing raw bytecode.

### From Whitelist to Fine-Grained
Historically, Docker’s default seccomp profile was a broad whitelist—allowing nearly all syscalls except a few explicitly denied. This "catch-all" approach was convenient but left a large attack surface. Fine-grained profiles invert the logic: start from an empty set and only add the syscalls your workload genuinely needs. The result is a profile that blocks `mount`, `chmod`, `pivot_root`, and dozens of other syscalls by default, while permitting `read`, `write`, `open`, `connect`, and the minimal set required for your application’s runtime.

The shift from whitelist to fine-grained requires two things: (1) a clear inventory of required syscalls for your stack, and (2) tooling that can translate that inventory into a valid BPF program. We’ll cover both.

## Building Profiles in Practice
### Docker Seccomp Profiles
Docker ships with a default profile located at `/etc/docker/seccomp/default.json`. This profile is actually a whitelist in JSON format that Docker’s own converter translates into BPF. To create a custom profile, you write a JSON array of allowed syscalls and their arguments, then pass it to Docker at runtime via `--security-opt seccomp=path/to/profile.json`.

A minimal profile for a Node.js server might look like:
```json
[
  {
    "action": "allow",
    "names": ["read", "write", "open", "close", "connect", "bind", "listen", "accept", "getdents", "dup", "dup2", "dup3"]
  },
  {
    "action": "allow",
    "names": ["exit", "exit_group"]
  },
  {
    "action": "errno",
    "names": ["socket", "bind", "listen"],
    "args": [
      {
        "index": 1,
        "value": 2, /* AF_INET */
        "op": "EQ"
      }
    ]
  }
]
```
Docker’s seccomp parser supports `allow`, `errno`, and `kill` actions, plus argument filtering for precise control. For example, you can allow `socket` only when the address family is `AF_INET` (value 2), blocking `AF_UNIX` or `AF_INET6` sockets entirely.

### Kubernetes Seccomp Integration
Kubernetes makes fine-grained seccomp declarative through the `spec.securityContext.seccompProfile` field in Pod and Container specifications. You can reference a pre-built profile by name, or inline a JSON profile.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: seccomp-demo
spec:
  securityContext:
    seccompProfile:
      type: Localhost
      localObjectPath: /etc/seccomp-profiles/my-web-profile.json
  containers:
  - name: my-web
    image: nginx:1.25
```
The `type: Localhost` means the profile must reside on the node at the given path. Alternatively, you can embed the profile directly:
```yaml
    seccompProfile:
      type: RuntimeDefault
      # inline profile JSON would go here
```
Kubernetes also supports `Unconfined` type, which disables seccomp entirely—avoid this unless you have a specific compatibility requirement.

For cluster-wide distribution, many teams store profiles in a ConfigMap or use the `seccomp-profiles` project maintained by the community, which provides hardened profiles for popular runtimes (Redis, PostgreSQL, Java, etc.).

### containerd Hook Workflow
containerd, the CNI runtime behind many Kubernetes distributions, supports seccomp through its `io.containerd.gcp.seccomp` hook in the task definition. This allows you to inject a seccomp profile during container creation, independent of the orchestration layer.

A minimal containerd task definition snippet:
```toml
[tasks."my-container"]
  ["io.containerd.gcp.seccomp"] = "/etc/seccomp-profiles/web-server.json"
```
This approach is useful when you want consistent seccomp enforcement across orchestrators, or when managing workloads directly via `ctr` without a full Kubernetes manifest.

## Real-World Profile Examples
### Minimal Web Server Profile
Consider a static nginx server serving over HTTPS. Required syscalls include `read`, `write`, `open`, `close`, `connect`, `bind`, `listen`, `accept`, `getdents` (directory reading for autoindex), `dup`, `dup2`, `dup3`, `exit`, `exit_group`, and `gettimeofday`. A fine-grained profile blocks everything else.

```json
[
  {"action": "allow", "names": ["read", "write"]},
  {"action": "allow", "names": ["open", "close"]},
  {"action": "allow", "names": ["connect", "bind", "listen", "accept"]},
  {"action": "allow", "names": ["getdents"]},
  {"action": "allow", "names": ["dup", "dup2", "dup3"]},
  {"action": "allow", "names": ["exit", "exit_group"]},
  {"action": "allow", "names": ["gettimeofday"]},
  {"action": "errno", "names": ["*"]}
]
```
The final `errno` rule with `names: ["*"]` acts as a catch-all: any syscall not explicitly allowed returns `errno` (typically `ENOSYS`), causing the application to fail fast with a clear error rather than silently continuing with a reduced feature set.

### GPU-Accelerated Workload Profile
A CUDA-based workload needs a completely different set: `open`, `write`, `ioctl`, `mmap`, `mprotect`, `brk`, `sbrk`, `exit`, `exit_group`, plus `clock_gettime` for timing. Additionally, `cudaGraphicsGLRegisterImage` may require `eventfd`, `eventfd2`, and `sync` (if using newer APIs). A profile for this scenario:

```json
[
  {"action": "allow", "names": ["open", "close"]},
  {"action": "allow", "names": ["read", "write"]},
  {"action": "allow", "names": ["ioctl", "mmap", "mprotect"]},
  {"action": "allow", "names": ["brk", "sbrk"]},
  {"action": "allow", "names": ["exit", "exit_group"]},
  {"action": "allow", "names": ["clock_gettime", "gettimeofday"]},
  {"action": "allow", "names": ["eventfd", "eventfd2"]},
  {"action": "errno", "names": ["*"]}
]
```
Notice how `socket`, `fork`, `vfork`, `clone`, and `ptrace` are absent—these are common vectors for container escape and are unnecessary for a compute-only workload.

## Debugging and Validation
### Using auditd for Syscall Auditing
Before locking down a profile, you need to know which syscalls your workload actually uses. Linux’s `auditd` subsystem can log every syscall the process makes, without enforcing restrictions. Start your container with `audit=1` or use `auditctl -w / -p rw -k seccomp-audit`, then run your workload and examine `/var/log/audit/audit.log`.

Example filter to extract relevant entries:
```bash
ausearch -k seccomp-audit | awk '{print $NF}' | sort | uniq -c | sort -rn
```
This yields a frequency table: `openat` might top the list at 12,000 calls per minute, while `pivot_root` never appears. Use this data to trim your profile from the bottom up—remove the least-frequent, highest-risk syscalls first.

### Common Pitfalls
1. **Blocking `write` to stderr**: Many libraries log to `stderr` via `write(2)`. If your profile blocks `write` without also allowing `open` on `/dev/stderr` or redirecting logs, your application will hang or crash with cryptic errors.
2. **Over-permissive `errno` catch-all**: While `errno` is safer than `allow`, an unqualified `errno` on `names: ["*"]` can mask bugs. Your app may fail with `ENOSYS` on perfectly valid calls, leading to confusing support tickets.
3. **Forgetting architecture-specific syscalls**: `arch_prctl` on x86_64, `sysinfo` on ARM, or `finit_module` for module loading. Always validate your profile on the target architecture.
4. **Inline profiles in CI, not production**: A profile that works in a CI job may miss runtime syscalls discovered only under load. Promote profiles through stages and audit at each step.

## Key Takeaways
- **Fine-grained seccomp inverts the default**: start empty, add only what’s needed, deny everything else.
- **Tooling matters**: use `bpffs`, Docker’s JSON-to-BPF converter, or Kubernetes’ `seccompProfile` to avoid hand-writing raw BPF bytecode.
- **Audit before you enforce**: leverage `auditd` to profile real syscall usage before freezing a profile.
- **Profile by workload**: a web server’s needs differ from a data pipeline, a GPU job, or a sidecar proxy. One size does not fit all.
- **Enforce declaratively**: embed profiles in Pod specs, containerd hooks, or Docker run flags, and treat them as versioned artifacts alongside your Dockerfiles.
- **Test the failure mode**: ensure your application degrades gracefully when a syscall is denied—prefer explicit errors over silent data loss.

## Further Reading
- [seccomp(2) man page](https://man7.org/linux/man-pages/man2/seccomp.2.html)
- [Docker seccomp documentation](https://docs.docker.com/engine/security/seccomp/)
- [Kubernetes seccomp profile guide](https://kubernetes.io/docs/concepts/security/seccomp/)
- [Google BPF Compiler Collection (bccl)](https://github.com/google/bpf-clang)
- [Linux kernel seccomp documentation](https://www.kernel.org/doc/html/latest/admin-guide/linux-features/seccomp.html)
- [containerd seccomp hook reference](https://containerd.io/docs/reference/configuration/seccomp/)

---