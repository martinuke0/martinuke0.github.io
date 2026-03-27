---
title: "Mastering nohup: Running Unix Processes Without Hangups"
date: "2026-03-27T10:23:15.121"
draft: false
tags: ["nohup", "linux", "unix", "shell", "process-management"]
---

## Introduction

When you log into a Unix or Linux system over SSH, you’re essentially opening a **session** that is bound to a controlling terminal. As long as that terminal exists, the kernel delivers signals—most notably `SIGHUP` (hang‑up)—to every process that belongs to the session. If the terminal disappears (for example, you close your SSH client or lose network connectivity), the kernel sends `SIGHUP` to the foreground and background jobs, and many of those jobs terminate by default.

For system administrators, developers, and data engineers, this behavior is often undesirable. You may want a long‑running data pipeline, a backup script, or a custom daemon to survive the disconnection of the terminal that launched it. This is where **`nohup`** (short for *no hang‑up*) comes into play.

In this article we will explore `nohup` from every angle:

* The historical context and why the utility exists.
* The low‑level mechanics of signal handling.
* Practical command‑line patterns and pitfalls.
* Comparisons with alternative tools (`disown`, `screen`, `tmux`, `systemd`).
* Real‑world scenarios where `nohup` shines.
* Best‑practice guidelines for secure, maintainable usage.

By the end, you should be able to confidently launch resilient background jobs on any POSIX‑compatible system, understand the trade‑offs, and decide when `nohup` is the right tool for the job.

---

## 1. What Is `nohup`? – History and Purpose

`nohup` originated in the early days of Unix as a simple wrapper that ignored the `SIGHUP` signal and redirected standard output/error to a file when the user’s terminal vanished. Its source code is tiny—often just a few dozen lines—and it ships with the GNU coreutils package on Linux, BSDs, macOS, and many embedded systems.

### 1.1 The Original Use‑Case

Consider a scenario in the 1970s: an astronomer logs into a mainframe via a teletype, starts a long‑running simulation, and then needs to step away. If the teletype line disconnects, the simulation would receive `SIGHUP` and abort, wasting hours of compute time. By invoking `nohup`, the astronomer could detach the process from the terminal, letting the simulation continue even if the line dropped.

### 1.2 Modern Relevance

Even though we now have sophisticated job‑scheduling frameworks (systemd, cron, Kubernetes), `nohup` remains valuable:

* **Quick ad‑hoc tasks** – launching a script while you’re still in an interactive shell.
* **Legacy environments** – where installing a full‑featured terminal multiplexer isn’t possible.
* **Minimalist containers** – where you want to keep the image small and avoid a heavyweight init system.

---

## 2. How `nohup` Works – Signal Handling Under the Hood

To understand why `nohup` does what it does, we need a brief dive into Unix signal mechanics.

### 2.1 The `SIGHUP` Signal

* **Signal number**: 1
* **Default action**: terminate the process.
* **When it’s sent**: The kernel sends `SIGHUP` to the foreground process group of a terminal when the terminal disconnects. It also propagates to jobs that are **still attached** to that session.

### 2.2 Ignoring `SIGHUP`

When a process calls `signal(SIGHUP, SIG_IGN)`, the kernel marks the signal as ignored for that process (and any of its children that inherit the disposition). `nohup` simply does this before executing the target command.

In C pseudo‑code:

```c
int main(int argc, char *argv[]) {
    // Ignore SIGHUP
    signal(SIGHUP, SIG_IGN);

    // If stdout is a terminal, redirect to nohup.out
    if (isatty(STDOUT_FILENO))
        freopen("nohup.out", "a", stdout);

    // Same for stderr if it’s still a terminal
    if (isatty(STDERR_FILENO))
        dup2(STDOUT_FILENO, STDERR_FILENO);

    // Exec the user command
    execvp(argv[1], &argv[1]);
}
```

That’s essentially the entire logic. The utility also sets the **process group ID** of the child to the same as the parent, but the crucial part is the ignored `SIGHUP`.

### 2.3 Redirection Behavior

If you do **not** explicitly redirect stdout/stderr, `nohup` will:

* Append stdout to a file named `nohup.out` in the current working directory.
* If `nohup.out` cannot be created (e.g., permission denied), it falls back to `$HOME/nohup.out`.
* Duplicate stdout to stderr, so both streams end up in the same file.

Because of this, many users explicitly redirect streams to avoid clutter or to separate logs.

---

## 3. Basic Usage – The “Hello World” of `nohup`

The canonical syntax is:

```bash
nohup COMMAND [ARG]... &
```

* `nohup` – the wrapper.
* `COMMAND` – the program you want to run.
* `&` – puts the command in the background **after** `nohup` sets up the environment.

### 3.1 A Simple Example

```bash
$ nohup sleep 300 &
[1] 12345
$ jobs
[1]+  Running                 nohup sleep 300 &
```

* The `sleep` command will continue for 5 minutes even if you close the terminal.
* Since `sleep` produces no output, `nohup` creates an empty `nohup.out` file.

### 3.2 Checking the Log

```bash
$ cat nohup.out
# (nothing, because sleep produced no output)
```

If you run a command that writes to stdout/stderr, you’ll see the output:

```bash
$ nohup bash -c 'for i in {1..5}; do echo "tick $i"; sleep 1; done' &
[2] 12346
$ cat nohup.out
tick 1
tick 2
tick 3
tick 4
tick 5
```

---

## 4. Combining `nohup` with Redirection

While the default `nohup.out` works for quick tests, production scripts usually require explicit log handling.

### 4.1 Redirecting Stdout Only

```bash
nohup my_script.sh > my_script.log &
```

* `my_script.log` receives only stdout.
* Stderr still gets duplicated to stdout **unless** you also redirect it.

### 4.2 Redirecting Both Streams Separately

```bash
nohup my_script.sh > my_script.out 2> my_script.err &
```

* `my_script.out` – standard output.
* `my_script.err` – error output.

### 4.3 Merging Both Streams into One File

```bash
nohup my_script.sh > my_script.log 2>&1 &
```

* `2>&1` tells the shell to send file descriptor 2 (stderr) to wherever fd 1 (stdout) is currently pointing.

### 4.4 Using `tee` for Real‑Time Monitoring

If you want to keep a log file **and** watch the output live:

```bash
nohup my_script.sh 2>&1 | tee -a my_script.log &
```

* Note: The pipeline (`|`) runs **outside** `nohup`. To keep the whole pipeline immune to `SIGHUP`, you can wrap it:

```bash
nohup sh -c 'my_script.sh 2>&1 | tee -a my_script.log' &
```

---

## 5. `nohup` vs. Alternatives – When to Choose Which Tool

`nohup` is not the only way to detach a process. Below is a comparative matrix.

| Feature | `nohup` | `disown` (bash built‑in) | `screen`/`tmux` | `systemd` (service unit) | `at` / `cron` |
|--------|---------|--------------------------|----------------|--------------------------|----------------|
| **Signal handling** | Ignores `SIGHUP` automatically | Must manually `disown` after backgrounding | Session isolation, detach/attach | Managed by init, not a terminal session | Runs without terminal |
| **Log management** | Default `nohup.out`; manual redirection | Same as parent shell | Can scroll back, attach later | Journald or custom logs | Cron logs, mail |
| **Interactive use** | Limited (no re‑attach) | No re‑attach | Full interactive terminal re‑attach | Not interactive | Non‑interactive |
| **Portability** | POSIX, all Unix‑like | Bash‑specific | Requires tmux/screen install | Systemd‑only (Linux) | Universal |
| **Complex pipelines** | Needs wrapper (`sh -c`) | Same as normal shell | Easy, each pane is a pty | Define in unit file | Use script |
| **Resource overhead** | Minimal (single process) | Minimal | Moderate (pseudo‑tty) | Higher (daemon) | Minimal |

### 5.1 When to Prefer `nohup`

* **One‑off background jobs** launched from a shell.
* **Minimal environments** where installing extra packages isn’t possible.
* **Scripts that must survive** a user disconnect but don’t need interactive re‑attachment.

### 5.2 When to Use `screen`/`tmux`

* You need to **re‑attach** later to an interactive session (e.g., monitoring a long‑running REPL).
* You want multiple windows/panes for parallel processes.

### 5.3 When to Use `systemd` Services

* The job is **long‑lived**, starts at boot, and requires **restart policies**, resource limits, or dependency management.
* You need **structured logging** via journald.

---

## 6. Using `nohup` in Scripts and Cron Jobs

Embedding `nohup` in a script is straightforward, but there are subtle nuances when combined with cron.

### 6.1 Script Example

```bash
#!/usr/bin/env bash
# backup.sh – runs a nightly rsync backup

set -euo pipefail

SRC="/data"
DEST="/backup/server"
LOG="/var/log/backup-$(date +%F).log"

nohup rsync -avz --delete "$SRC/" "$DEST/" > "$LOG" 2>&1 &
echo "Backup started, PID=$!; log at $LOG"
```

* The script launches `rsync` in the background, writes a timestamped log, and exits immediately.
* The parent script can continue with other tasks or simply finish.

### 6.2 Cron Integration

Cron already runs jobs **without a controlling terminal**, so `SIGHUP` is not an issue. However, you may still want `nohup` if your command spawns background processes that should not be killed when the cron job finishes.

```cron
0 2 * * * /usr/local/bin/backup.sh >> /var/log/cron.log 2>&1
```

If `backup.sh` itself launches background jobs (as above), using `nohup` ensures those background processes survive the termination of the cron child process.

### 6.3 Pitfalls with Cron

* **Environment variables**: Cron provides a minimal environment. Always use absolute paths or source a profile within the script.
* **PATH**: `nohup` is usually in `/usr/bin/nohup`. Use the full path if you’re unsure.
* **Mail spam**: Cron emails output. Redirect everything to a log file to avoid unwanted mail.

---

## 7. Advanced Examples

### 7.1 Long‑Running Data Pipeline

```bash
#!/usr/bin/env bash
# pipeline.sh – ingest, transform, and store data

set -euo pipefail

INPUT="/data/raw/*.json"
TRANSFORM="/usr/local/bin/transformer"
STORE="/usr/local/bin/store_results"

nohup bash -c '
    for file in '"$INPUT"'; do
        echo "Processing $file"
        cat "$file" | '"$TRANSFORM"' | '"$STORE"'
    done
' > /var/log/pipeline.log 2>&1 &
echo "Pipeline started with PID $!"
```

* The entire pipeline runs in a subshell invoked by `nohup`, ensuring that the `for` loop and all child processes ignore `SIGHUP`.

### 7.2 Rotating Logs with `logrotate`

If you want `nohup.out` to be rotated automatically, configure `logrotate`:

```conf
/var/log/myapp/nohup.out {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
```

* `copytruncate` copies the current file and truncates it, allowing the running process to continue writing to the same file descriptor.

### 7.3 Running Inside Docker Containers

In minimal Docker images, you often lack an init system. If you need a “fire‑and‑forget” background job, use `nohup`:

```dockerfile
FROM alpine:3.18
RUN apk add --no-cache coreutils
COPY myscript.sh /usr/local/bin/
CMD ["sh", "-c", "nohup /usr/local/bin/myscript.sh > /var/log/myscript.log 2>&1 & tail -f /dev/null"]
```

* The `tail -f /dev/null` keeps the container alive while the background script runs.

---

## 8. Portability and Compatibility

### 8.1 POSIX Guarantees

`nohup` is defined by the POSIX specification, which means any compliant system must provide it. The behavior is consistent across:

* Linux (glibc, musl)
* BSD (FreeBSD, OpenBSD, NetBSD)
* macOS (Darwin)
* Solaris (OpenSolaris derivatives)

### 8.2 Windows Considerations

Native Windows does **not** have a `nohup` binary. However, you can achieve similar behavior:

* **WSL (Windows Subsystem for Linux)** – install a Linux distribution and use `nohup` as usual.
* **PowerShell** – use `Start-Process -NoNewWindow -RedirectStandardOutput` or `Start-Job`.
* **Cygwin/MSYS2** – provide a Unix‑like environment with `nohup`.

---

## 9. Common Pitfalls and Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `nohup: ignoring input and appending output to 'nohup.out'` appears even after explicit redirection | Redirection placed **after** `nohup` but before `&`? Actually redirection works, but you may have a stray `</dev/null` in your script. | Verify order: `nohup cmd >out 2>&1 &`. |
| Process still dies when terminal closes | The command **forks** and the child **resets** signal disposition. | Use `nohup sh -c 'cmd1 & cmd2'` or wrap the entire pipeline in a subshell. |
| `nohup.out` is empty, but the program writes to a file | The program writes directly to its own log file; `nohup` only redirects stdout/stderr. | No issue; just check program‑specific logs. |
| `Permission denied` when creating `nohup.out` | Current directory not writable. | Specify a log path you own: `nohup cmd > ~/cmd.log 2>&1 &`. |
| Background job shows up as `[1]+ Stopped` after `nohup` | The job received a `SIGTSTP` (Ctrl‑Z) before `nohup` ignored `SIGHUP`. | Ensure you start the command without sending it to background manually first. |
| `nohup` not found | Minimal container missing coreutils. | Install `coreutils` (`apk add coreutils` or `apt-get install coreutils`). |

### 9.1 Debugging with `ps` and `strace`

```bash
$ ps -ef | grep mycmd
$ strace -e trace=signal -p <pid>
```

* `strace` can confirm that `SIGHUP` is being ignored (`SIG_IGN`).

---

## 10. Best Practices and Security Considerations

1. **Explicit Redirection** – Never rely on the default `nohup.out`. Specify a log file in a directory with proper permissions.
2. **Avoid Running as Root** – If the command doesn’t need elevated privileges, drop them before invoking `nohup`.
3. **Use Full Paths** – Cron and minimal containers have limited `$PATH`. Write `/usr/bin/nohup` or add `PATH` explicitly.
4. **Limit Resource Usage** – `nohup` itself doesn’t enforce limits. Combine with `ulimit` or `cgroups` if needed.
   ```bash
   ulimit -n 1024   # limit open files
   nohup mycmd &
   ```
5. **Graceful Shutdown** – Since `nohup` ignores `SIGHUP`, you must send a different signal to stop the process (`SIGTERM` or `SIGINT`).
   ```bash
   kill -TERM <pid>
   ```
6. **Log Rotation** – Pair with `logrotate` to prevent unbounded log growth.
7. **Documentation** – Comment scripts that use `nohup` so future maintainers understand why the utility is there.

---

## 11. Real‑World Use Cases

### 11.1 Continuous Integration (CI) Workers

A CI server may need to trigger a long‑running build on a remote machine via SSH. Using `nohup` ensures the build continues even if the SSH session drops:

```bash
ssh user@builder "nohup ./run_build.sh > build.log 2>&1 &"
```

### 11.2 Remote Data Collection

IoT gateways often have flaky network connections. A data‑collector script runs locally, pushes data to the cloud, and must survive network outages:

```bash
nohup ./collector.sh > /var/log/collector.log 2>&1 &
```

### 11.3 One‑Off Database Migrations

During a maintenance window, a DBA may start a migration script that takes several hours. To avoid being tied to a terminal, they use:

```bash
nohup psql -f migrate.sql > migrate.log 2>&1 &
```

If the SSH session disconnects, the migration continues, and the log file provides a post‑mortem.

---

## Conclusion

`nohup` is a deceptively simple tool that embodies a core Unix philosophy: **do one thing and do it well**. By ignoring the `SIGHUP` signal and handling default output redirection, it gives you a reliable way to detach processes from a terminal without the overhead of a full‑blown terminal multiplexer or init system.

While alternatives like `screen`, `tmux`, `disown`, and `systemd` cover broader use‑cases, `nohup` remains the go‑to utility for quick, low‑dependency background jobs. Understanding its internals—how it manipulates signal dispositions and file descriptors—helps you avoid common pitfalls and integrate it safely into scripts, cron jobs, Docker containers, and remote automation pipelines.

Remember to:

* Explicitly redirect output.
* Use full paths in constrained environments.
* Pair `nohup` with log rotation and resource limits.
* Choose the right tool for the job.

Armed with these best practices, you can confidently keep your jobs running, even when your terminal does not.

---

## Resources

* [GNU Coreutils – `nohup` Manual](https://www.gnu.org/software/coreutils/manual/html_node/nohup-invocation.html) – Official documentation and options.
* [The Linux Programming Interface – Signal Handling](https://man7.org/tlpi/) – In‑depth explanation of Unix signals, including `SIGHUP`.
* [Systemd Service Files – Documentation](https://www.freedesktop.org/software/systemd/man/systemd.service.html) – When to prefer systemd over `nohup`.
* [Logrotate – Manual](https://linux.die.net/man/8/logrotate) – Managing rotating logs for `nohup.out`.
* [Dockerfile Best Practices – Official Guide](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/) – Using `nohup` inside minimal containers.