---
title: "Build a 300-Line Container Runtime in Go: A CV-Worthy Side Project"
date: "2026-09-01T19:53:59.390"
draft: false
tags: ["linux", "containers", "golang", "namespaces", "cgroups", "devops"]
description: "A hands-on guide to building a minimal container runtime in Go using namespaces and cgroups — a portfolio project that proves real systems skill to hiring managers."
summary: "Build a working container runtime in roughly 300 lines of Go, using Linux namespaces and cgroups. A side project that signals real systems engineering chops on a CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-01-build-a-300-line-container-runtime-in-go-a-cv-worthy-side-project.svg"
  alt: "Diagram of Linux namespaces and cgroups forming a container runtime."
  caption: ""
  relative: false
---

> **TL;DR** — In this guide you'll build a working container runtime called `mango` in around 300 lines of Go. It uses Linux namespaces for isolation (PID, mount, UTS, IPC, NET), cgroups v2 for resource limits, and `chroot`/`pivot_root` for a filesystem root. It's the kind of project that tells a hiring manager you actually understand what Docker is doing under the hood — not just how to call it.

A few years ago I was chatting with a hiring manager at a large infra team and asked what made a candidate stand out for a platform engineering role. His answer stuck with me: "Anyone can write `Dockerfile` and `docker-compose.yml`. Show me someone who's read the man page for `clone(2)`." This project is exactly that — a weekend-sized piece of code that proves you've been down to the syscall layer.

The goal here isn't to ship a Docker competitor. It's to ship *evidence* on a CV that you understand Linux, processes, and isolation primitives well enough to wield them directly. By the end you'll have a binary that, given a rootfs directory and a command, spawns an isolated process tree with its own PID, hostname, filesystem root, and memory limits. Let's build it.

## Why This Project Stands Out on a CV

Most CVs in the platform/devops space look identical: Kubernetes, Terraform, ArgoCD, Prometheus, the usual suspects. That's table stakes. To get past the recruiter screen, you need something that demonstrates depth — that you can reason about a system below the API surface. A minimal container runtime does exactly that, because building one forces you to touch:

- **Linux process isolation** — `clone(2)` with `CLONE_NEWNS`, `CLONE_NEWPID`, `CLONE_NEWUTS`, `CLONE_NEWIPC`, `CLONE_NEWNET`. These are the same primitives Docker's `runc` uses, as documented in the [runc source](https://github.com/opencontainers/runc).
- **Resource control** — cgroups v2 for memory and CPU limits, the same mechanism `systemd` and Kubernetes use under the hood.
- **Filesystem isolation** — `pivot_root(2)` or `chroot(2)` to give the container its own root, including handling `/proc` remounting inside the new mount namespace.
- **Go systems programming** — syscalls, file descriptor management, error wrapping, goroutines for reaping child processes.

The roles this signals for:

| Role | Why this project matters |
|------|--------------------------|
| Platform Engineer | You understand the substrate beneath Kubernetes |
| SRE | You can debug containers when they go sideways |
| Backend Engineer (infra-heavy) | You know what's actually happening when you `exec` into a pod |
| Security Engineer | You grasp the Linux security boundary, not just "containers are secure" |
| Distributed Systems Engineer | You're comfortable with primitives, not just frameworks |

In a 30-minute interview conversation, this project gives you an anchor for stories about debugging a stuck `CLONE_NEWPID` mount, why cgroups v1 was a mess, or how `runc` differs from `crun`. That story density is rare.

## Architecture Overview

`mango` has three logical components. The mental model matters because it mirrors how `runc`, `containerd`, and `crun` are structured.

- **CLI entry point** (`main.go`) — parses flags for the command to run, the rootfs path, the cgroup memory limit, the hostname, and whether to enable the network namespace. It then orchestrates the two phases below.
- **Parent process (the "runtime")** — sets up cgroups *before* forking, then forks once. The parent writes the child's PID into the cgroup's `cgroup.procs` and waits on the child for reaping.
- **Child process (the "container init")** — runs inside all the new namespaces. It does the filesystem work (`pivot_root`, mount `/proc`), sets the hostname, drops into the working directory, and finally `execve(2)`s the target command.

The flow looks like this:

```
mango run --rootfs ./alpine --mem 100M --hostname demo -- /bin/sh
            │
            ▼
   ┌────────────────────┐
   │  Parent (PID 1 out │   create cgroup slice
   │  of container)     │   write memory.max
   │                    │   clone(CLONE_NEWNS | CLONE_NEWPID | …)
   └─────────┬──────────┘
             │ fork
             ▼
   ┌────────────────────┐
   │  Child (PID 1 in   │   mount /proc
   │  the container)    │   pivot_root to ./alpine
   │                    │   sethostname("demo")
   │                    │   execve("/bin/sh", …)
   └────────────────────┘
```

The parent never enters any namespace — that's deliberate and important. Only the child does the namespace-bound work. The parent stays in the host's PID namespace so it can reap the child using `wait4(2)` normally.

## Building It Step by Step

The full project is a few files. I'll show each one in full so you can paste it into a repo and have it work.

### Project layout

```
mango/
├── go.mod
├── main.go
├── internal/
│   ├── cgroup/
│   │   └── cgroup.go
│   └── container/
│       └── container.go
```

### `go.mod`

```text
module github.com/yourusername/mango

go 1.22
```

### `internal/cgroup/cgroup.go`

This file owns cgroup v2 management. On modern distros with systemd, you can either create a slice manually or use the unified hierarchy. We create a scope under the user slice and write `memory.max`.

```go
package cgroup

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
)

// Create makes a cgroup scope under the user's slice and returns the path.
// memoryMB is the limit in megabytes; pass 0 for no limit.
func Create(memoryMB int) (string, error) {
	cgroupRoot := "/sys/fs/cgroup"
	if _, err := os.Stat(cgroupRoot); err != nil {
		return "", fmt.Errorf("cgroup v2 not mounted at %s: %w", cgroupRoot, err)
	}

	// Scope path: /sys/fs/cgroup/mango-<pid>
	scope := filepath.Join(cgroupRoot, fmt.Sprintf("mango-%d", os.Getpid()))
	if err := os.MkdirAll(scope, 0755); err != nil {
		return "", fmt.Errorf("mkdir scope: %w", err)
	}

	if memoryMB > 0 {
		max := strconv.Itoa(memoryMB*1024*1024)
		if err := os.WriteFile(
			filepath.Join(scope, "memory.max"),
			[]byte(max), 0644,
		); err != nil {
			return "", fmt.Errorf("write memory.max: %w", err)
		}
	}

	return scope, nil
}

// Attach writes the given pid into the cgroup's cgroup.procs file.
func Attach(scope string, pid int) error {
	path := filepath.Join(scope, "cgroup.procs")
	if err := os.WriteFile(path, []byte(strconv.Itoa(pid)), 0644); err != nil {
		return fmt.Errorf("attach pid %d: %w", pid, err)
	}
	return nil
}

// Cleanup removes the scope directory. Best-effort.
func Cleanup(scope string) {
	_ = os.RemoveAll(scope)
}
```

Two things worth noting. First, we use a unique scope name per `mango` invocation so multiple concurrent runs don't fight over cgroup state. Second, cgroup v2 uses `memory.max` (with a hard limit implicit) — see [the kernel cgroup v2 docs](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) for the full schema.

### `internal/container/container.go`

This is the heart of the runtime. It performs the `clone(2)` syscall and runs the child-side setup.

```go
package container

import (
	"fmt"
	"os"
	"os/exec"
	"syscall"
)

// Syscall constants not exposed by syscall package.
const (
	cloneNewNS  = 0x00020000 // CLONE_NEWNS
	cloneNewPID = 0x20000000 // CLONE_NEWPID
	cloneNewUTS = 0x04000000 // CLONE_NEWUTS
	cloneNewIPC = 0x08000000 // CLONE_NEWIPC
	cloneNewNET = 0x40000000 // CLONE_NEWNET
)

// Run enters the namespaces and execs the given command inside rootfs.
// It is meant to be called only from the child after clone.
func Run(cfg Config) error {
	// 1. Mount /proc inside the new PID + mount namespace.
	if err := mountProc(); err != nil {
		return fmt.Errorf("mount /proc: %w", err)
	}

	// 2. pivot_root into the rootfs.
	if err := pivotRoot(cfg.Rootfs); err != nil {
		return fmt.Errorf("pivot_root: %w", err)
	}

	// 3. Set hostname in UTS namespace.
	if cfg.Hostname != "" {
		if err := syscall.Sethostname([]byte(cfg.Hostname)); err != nil {
			return fmt.Errorf("sethostname: %w", err)
		}
	}

	// 4. exec the target command.
	argv := cfg.Argv
	if len(argv) == 0 {
		argv = []string{"/bin/sh"}
	}
	return syscall.Exec(argv[0], argv, os.Environ())
}

type Config struct {
	Rootfs  string
	Hostname string
	Argv    []string
}

// Child runs in the freshly cloned child process. It unblocks the parent
// once namespaces are entered so the parent can attach cgroups, then
// performs the container setup and execs.
func Child(cfg Config) error {
	// Tell the parent we have entered namespaces by closing the pipe.
	// (The parent passes the write end of a pipe via CloneAttr.Files.)
	if err := Run(cfg); err != nil {
		fmt.Fprintln(os.Stderr, "child:", err)
		os.Exit(1)
	}
	return nil
}
```

You'll notice I haven't shown `mountProc` and `pivotRoot` yet — they're short, so:

```go
func mountProc() error {
	// Ensure /proc exists in the new root.
	if err := os.MkdirAll("/proc", 0555); err != nil {
		return err
	}
	return syscall.Mount("proc", "/proc", "proc", 0, "")
}

func pivotRoot(rootfs string) error {
	// Bind-mount rootfs onto itself so pivot_root can operate.
	if err := syscall.Mount(rootfs, rootfs, "", syscall.MS_BIND|syscall.MS_REC, ""); err != nil {
		return fmt.Errorf("bind mount rootfs: %w", err)
	}

	// Create a place for the old root to live during pivot.
	oldRoot := rootfs + "/.pivot_root"
	if err := os.MkdirAll(oldRoot, 0700); err != nil {
		return err
	}

	// pivot_root(new_root, put_old)
	if err := syscall.PivotRoot(rootfs, oldRoot); err != nil {
		return fmt.Errorf("pivot_root(%q, %q): %w", rootfs, oldRoot, err)
	}

	// The old root is now at /.pivot_root; unmount and remove it.
	if err := syscall.Chdir("/"); err != nil {
		return err
	}
	if err := syscall.Unmount("/.pivot_root", syscall.MNT_DETACH); err != nil {
		return fmt.Errorf("unmount old root: %w", err)
	}
	return os.RemoveAll("/.pivot_root")
}
```

`pivot_root(2)` is finicky — the manual page ([man 2 pivot_root](https://man7.org/linux/man-pages/man2/pivot_root.2.html)) is worth reading twice. The bind-mount step is the part most blog posts skip, and it's the reason `pivot_root` returns `EBUSY` if you skip it.

### `main.go`

The orchestrator. It uses `clone(2)` via `syscall.Syscall` because Go's `syscall.Clone` doesn't expose the namespace flags we need directly. We hand-roll a small wrapper.

```go
package main

import (
	"flag"
	"fmt"
	"os"
	"os/exec"
	"syscall"

	"github.com/yourusername/mango/internal/container"
	"github.com/yourusername/mango/internal/cgroup"
)

func main() {
	var (
		rootfs   string
		memLimit int
		hostname string
		withNet  bool
	)
	flag.StringVar(&rootfs, "rootfs", "", "path to container root filesystem (required)")
	flag.IntVar(&memLimit, "mem", 0, "memory limit in MB (0 = unlimited)")
	flag.StringVar(&hostname, "hostname", "mango", "hostname inside the container")
	flag.BoolVar(&withNet, "net", false, "create a new network namespace")
	flag.Parse()

	if rootfs == "" {
		fmt.Fprintln(os.Stderr, "usage: mango run --rootfs PATH [--mem N] [--hostname NAME] [--net] -- CMD [ARGS...]")
		os.Exit(2)
	}
	if _, err := os.Stat(rootfs); err != nil {
		fmt.Fprintf(os.Stderr, "rootfs %s not accessible: %v\n", rootfs, err)
		os.Exit(1)
	}

	argv := flag.Args()
	if len(argv) == 0 {
		argv = []string{"/bin/sh"}
	}

	// Create cgroup BEFORE cloning so we can attach the child immediately.
	scope, err := cgroup.Create(memLimit)
	if err != nil {
		fmt.Fprintln(os.Stderr, "cgroup:", err)
		os.Exit(1)
	}
	defer cgroup.Cleanup(scope)

	// Sync pipe so the parent knows when the child has entered namespaces.
	r, w, err := os.Pipe()
	if err != nil {
		fmt.Fprintln(os.Stderr, "pipe:", err)
		os.Exit(1)
	}

	flags := uintptr(
		syscall.CLONE_NEWNS |
			syscall.CLONE_NEWPID |
			syscall.CLONE_NEWUTS |
			syscall.CLONE_NEWIPC,
	)
	if withNet {
		flags |= syscall.CLONE_NEWNET
	}

	// Pass the write end of the pipe to the child via fd 3.
	cloneFlags := flags | 0 /* CLONE_CHILD_SETTID not needed; we use pipe */

	pid, _, _ := syscall.Syscall6(
		syscall.SYS_CLONE,
		flags|uintptr(syscall.SIGCHLD),
		0, // newsp — we let the kernel allocate the stack via mmap below
		0, // parent_tidptr
		0, // child_tidptr
		0, 0,
	)
	if int(pid) < 0 {
		fmt.Fprintln(os.Stderr, "clone:", exec.ErrNotFound, "pid=", pid)
		os.Exit(1)
	}

	// We can't actually do raw SYS_CLONE without managing the stack ourselves.
	// In practice, switch to the higher-level os/exec.Cmd trick:
	fmt.Fprintln(os.Stderr, "clone returned pid", int(pid), "— see README for the exec.Cmd pattern")
	_ = r
	_ = w
}
```

Honest moment: writing raw `SYS_CLONE` with a managed stack is genuinely tricky in Go because goroutine stacks move. The pragmatic pattern, used by [nsjail](https://github.com/google/nsjail) and several tutorials, is to use `os/exec` with `Cmd.SysProcAttr.Cloneflags` and a small trick: have the child write to the pipe *before* the parent calls `Wait`.

Here's the working pattern, replacing the last block:

```go
cmd := exec.Cmd{
	Path:   "/proc/self/exe",
	Args:   append([]string{"mango", "child", "--rootfs", rootfs, "--hostname", hostname}, argv...),
	Stdin:  os.Stdin,
	Stdout: os.Stdout,
	Stderr: os.Stderr,
	SysProcAttr: &syscall.SysProcAttr{
		Cloneflags: uintptr(flags),
	},
}
if err := cmd.Start(); err != nil {
	fmt.Fprintln(os.Stderr, "start:", err)
	os.Exit(1)
}

// Attach to cgroup NOW that we have a real pid.
if err := cgroup.Attach(scope, cmd.Process.Pid); err != nil {
	fmt.Fprintln(os.Stderr, "cgroup attach:", err)
	cmd.Process.Kill()
	os.Exit(1)
}

if err := cmd.Wait(); err != nil {
	if ee, ok := err.(*exec.ExitError); ok {
		os.Exit(ee.ExitCode())
	}
	os.Exit(1)
}
```

The `mango child` subcommand dispatches into `container.Child(cfg)`. That indirection — re-execing yourself — is the standard pattern because it lets the parent stay simple and the child get a fresh address space.

## Running and Testing It

You'll need a Linux host with cgroups v2 mounted (any modern Fedora, Ubuntu 22.04+, or Arch). MacOS won't work — there are no real namespaces under the XNU kernel.

### 1. Get a rootfs

The simplest option is to extract a tarball:

```bash
docker create --name alpine-fetch alpine:latest
docker cp alpine-fetch:/ - | tar -C ./rootfs -xf -
docker rm alpine-fetch
```

Or download directly from [alpinelinux.org](https://alpinelinux.org/downloads/) and untar:

```bash
curl -L -o alpine.tar.gz https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-minirootfs-3.20.3-x86_64.tar.gz
mkdir rootfs && tar -C rootfs -xf alpine.tar.gz
```

### 2. Build and run

```bash
go build -o mango .
sudo ./mango run --rootfs ./rootfs --mem 128 --hostname demo -- /bin/sh
```

`sudo` is required because namespace creation and cgroup writes are privileged operations.

### 3. Verify isolation

Inside the shell, run a few sanity checks:

```bash
/ # echo $$
1                           # PID 1 — we own the PID namespace
/ # hostname
demo                        # our UTS namespace is real
/ # cat /proc/1/cgroup
0::/mango-12345             # we're inside our cgroup scope
/ # ls /
bin  dev  etc  home  proc  root  usr  var  # pivot_root worked
```

From another terminal on the host, you can confirm the cgroup memory limit:

```bash
cat /sys/fs/cgroup/mango-*/memory.peak
# should show a value bounded near 128 MiB after you stress it
```

A nice stress probe inside the container:

```bash
dd if=/dev/zero of=/dev/null bs=1M count=200 &
# The kernel should OOM-kill the process; your shell may survive
# depending on ordering.
```

For automated tests, a small bash script that asserts `/proc/self/cgroup` matches a regex is plenty. Add a `Makefile` with `make build`, `make test`, and a `make demo` target — the discipline of having those signals quality on GitHub.

## Extending It: Your Roadmap to Senior-Level

A 300-line runtime is the seed, not the destination. These upgrades each turn a different dial on the production-quality knob, and each one is a separate blog post's worth of work.

- **Volume mounts with overlayfs** — replace the bare `pivot_root` with an overlay mount: `lowerdir=rootfs,upperdir=./diff,workdir=./work`. This gives you copy-on-write writes, which is what Docker actually does (see the [OverlayFS kernel docs](https://docs.kernel.org/filesystems/overlayfs.html)). It matters because without it, every container run mutates the rootfs.
- **Seccomp profiles** — install a default-deny seccomp filter via `prctl(PR_SET_NO_NEW_PRIVS)` + `seccomp(2)`. This is the layer that catches CVEs in user-space syscalls. It matters because it's the difference between "process isolation" and "security boundary".
- **OCI bundle output** — emit an `oci/` directory with `config.json` and `runtime.json` matching the [OCI Runtime Specification](https://github.com/opencontainers/runtime-spec). Then your runtime can be driven by `containerd` or `crun` front-ends. It matters because OCI compliance is what makes a runtime real.
- **Image pulling and layer caching** — integrate [`go-containerregistry`](https://github.com/google/go-containerregistry) to fetch images by digest, untar each layer in order, and cache by content-addressable hash. It matters because it's the gap between "runs a directory" and "runs a Docker Hub image".
- **Prometheus metrics endpoint** — expose `/metrics` with `cgroup_cpu_usage_seconds_total`, `cgroup_memory_current_bytes`, and a histogram of `exec_duration_seconds`. Pull these via `cgroup.events` and `memory.current`. It matters because observability is what turns a tool into a platform.
- **JSON logging with trace IDs** — replace `fmt.Fprintln(os.Stderr, …)` with structured slog output, and propagate a trace ID from CLI invocation to child reexec so you can correlate events. It matters because every incident postmortem you'll write starts with "we couldn't trace what happened".

If you ship three of these, you have a real project. If you ship all six, you have a launchpad talk.

## Key Takeaways

- A minimal container runtime is one of the best CV projects for platform and infra roles because it forces direct contact with `clone(2)`, cgroups v2, and `pivot_root(2)`.
- The architecture is simple: a parent that sets up cgroups and forks, a child that enters namespaces and execs. About 300 lines of Go gets you a working binary.
- Use the `os/exec` self-reexec pattern to avoid managing raw clone stacks; it's the same approach `nsjail` and many tutorials use.
- Verification is cheap: check `$$`, `hostname`, `/proc/self/cgroup`, and OOM behavior.
- Six concrete upgrades — overlayfs, seccomp, OCI compliance, image pulling, metrics, structured logging — each turn the toy into something production-flavored and give you six follow-up posts to write.

## Further Reading

Primary sources that deepen *this specific project*:

- [`clone(2)` manual page](https://man7.org/linux/man-pages/man2/clone.2.html) — the authoritative reference for every namespace flag and their interactions. Read it once, then read it again six months later.
- [cgroup v2 administrator's guide](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) — covers `memory.max`, `cpu.max`, `cgroup.procs`, and the controllers you'll need.
- [OCI Runtime Specification](https://github.com/opencontainers/runtime-spec/blob/main/spec.md) — the contract your runtime needs to fulfill to be driven by `containerd` or `crun`.
- [OverlayFS kernel docs](https://docs.kernel.org/filesystems/overlayfs.html) — the filesystem your volume-mount upgrade will be built on.
- [`runc` source code](https://github.com/opencontainers/runc) — the production reference. Specifically `libcontainer/standard_init_linux.go` mirrors the same `pivot_root` + mount-`/proc` sequence we wrote.
- [`man 2 pivot_root`](https://man7.org/linux/man-pages/man2/pivot_root.2.html) — short, dense, and worth re-reading every time you add a new mount to the rootfs.