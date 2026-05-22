---
title: "Deep Dive into Flame Graphs: Visualizing Performance Bottlenecks and Identifying Hidden Execution Latency"
date: "2026-05-22T08:00:50.191"
draft: false
tags: ["performance", "flamegraphs", "profiling", "observability", "go"]
description: "Explore how flame graphs turn raw stack traces into actionable visualizations, with step‑by‑step pipelines, production patterns, and real‑world case studies."
summary: "A practical guide that shows engineers how to generate, interpret, and integrate flame graphs into modern observability stacks."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-22-deep-dive-into-flame-graphs-visualizing-performance-bottlenecks-and-identifying-hidden-execution-latency.svg"
  alt: "A colorful flame graph rendered from a high‑frequency stack trace."
  caption: ""
  relative: false
---

> **TL;DR** — Flame graphs turn massive stacks of sampled CPU data into a compact, color‑coded visualization that highlights hot paths. By wiring a small pipeline (perf → collapsed stack → flamegraph.pl) into CI/CD or live observability, you can spot hidden latency in Java, Go, Rust, or any native binary within minutes.

Performance engineers spend countless hours chasing “slow” endpoints, only to discover that the real culprit lives deep inside a library call or a GC pause. Traditional profiling tools give you raw numbers, but they rarely show the *shape* of the problem. Flame graphs fill that gap: they compress millions of stack frames into a hierarchical heat map where width equals time spent, and color encodes additional dimensions such as CPU core or thread ID. This post walks you through the theory, the production‑grade architecture, concrete tooling for Java, Go, and Rust, and the patterns you need to adopt to make flame graphs a first‑class part of your observability stack.

## What Is a Flame Graph?

A flame graph is a visual representation of stack trace samples collected over a period of execution. Each horizontal bar corresponds to a function (or method) and its width is proportional to the cumulative time spent in that function **and all its callees**. Stacks are stacked vertically: the bottom row represents leaf functions (the innermost calls), and each row above shows the caller. The resulting “flame” shape lets you instantly spot the widest bars—the hot paths.

### Origins and Core Idea

Brendan Gregg introduced flame graphs in 2010 to make performance data from tools like `perf`, `DTrace`, and `SystemTap easier to digest. The key insight is **collapsing identical stacks**: if the same call chain appears 10 000 times, you emit a single line `"main;process_request;handle_db;query"` with a count of 10 000. This “collapsed stack” format reduces a gigabyte of raw samples to a few megabytes, which a simple SVG generator can turn into a flame graph.

### Why Width Matters More Than Height

Traditional call graphs often list functions in alphabetical order or by call depth, which makes it hard to see *where* the time is spent. Flame graphs invert the problem: time is the primary axis. A narrow bar at the bottom may still be a performance issue if it represents a lock that serializes thousands of requests, but the first step is always to locate the *widest* region.

## Generating Flame Graphs in Production

Creating a flame graph is a three‑step pipeline:

1. **Sampling** – Capture stack traces at a fixed interval (e.g., 99 Hz) using a low‑overhead tool.
2. **Collapsing** – Convert raw samples into the collapsed format (`func1;func2;func3 count`).
3. **Rendering** – Feed the collapsed file to `flamegraph.pl` (or a compatible renderer) to produce an SVG.

Below is a minimal Bash script that you can drop into a CI job, a sidecar container, or a Kubernetes DaemonSet.

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Choose the target PID (or container ID)
PID=${1:-$(pgrep -f myservice)}
DURATION=${2:-30}          # seconds to sample
OUTPUT_DIR=${3:-/tmp/flames}
mkdir -p "$OUTPUT_DIR"

# 2. Record perf data (samples at 99 Hz, call graph)
perf record -F 99 -p "$PID" -g --output "$OUTPUT_DIR/perf.data" -- sleep "$DURATION"

# 3. Convert to collapsed stacks
perf script -i "$OUTPUT_DIR/perf.data" | \
  perl /usr/local/bin/stackcollapse-perf.pl > "$OUTPUT_DIR/collapsed.txt"

# 4. Render the SVG
perl /usr/local/bin/flamegraph.pl "$OUTPUT_DIR/collapsed.txt" \
  --title "Flame Graph for PID $PID (last $DURATION s)" \
  --colors "blue" > "$OUTPUT_DIR/flamegraph.svg"

echo "Flame graph written to $OUTPUT_DIR/flamegraph.svg"
```

> **Note** – The script assumes `stackcollapse-perf.pl` and `flamegraph.pl` are in `/usr/local/bin`. These are the original Perl utilities from Brendan Gregg’s repository. For Go or Rust binaries you may prefer `perf` + `--call-graph dwarf`, or the `perf inject --jit` flag for JIT‑compiled languages.

### Integrating with CI/CD

Running the script on a CI node gives you a *baseline* flame graph for each commit. Store the SVG as an artifact and compare it with the previous build using a diff tool like `flamegraph.pl --diff`. The diff output highlights newly introduced hot paths, making regression detection automatic.

```bash
# Example diff between two builds
perl /usr/local/bin/flamegraph.pl --diff \
  build-123/collapsed.txt build-124/collapsed.txt \
  > diff-123-124.svg
```

### Real‑World Sampling Rates

- **CPU‑bound services**: 99 Hz is a sweet spot—captures enough granularity without adding noticeable overhead (< 1 % on modern Xeon).
- **I/O‑heavy services**: Increase to 199 Hz if you need finer latency granularity; watch for increased overhead on busy cores.
- **Kubernetes pods**: Use `perf record -a -g -F 99 -p $(pgrep -f myservice)` inside a privileged sidecar. The sidecar writes the SVG to a shared emptyDir volume that your logging pipeline can ship to S3.

## Architecture of a Flame Graph Pipeline

When you move from ad‑hoc scripts to a production observability platform, three architectural concerns dominate:

1. **Data Collection Layer** – Agents that run on every host, container, or VM.
2. **Processing Layer** – Stateless services that collapse stacks and render SVGs.
3. **Storage & Visualization Layer** – Object storage for SVGs, dashboards for interactive exploration.

### Data Collection Layer

| Component | Typical Tool | Pros | Cons |
|-----------|--------------|------|------|
| Kernel‑level sampling | `perf` (Linux), `dtrace` (macOS) | Very low overhead, works for any native binary | Requires privileged access |
| User‑space sampling | `py-spy` (Python), `async-profiler` (Java) | No root needed, can attach to running processes | Language‑specific, may miss native frames |
| JIT‑aware sampling | `perf` with `--jit` | Captures Java/JS JIT frames | Needs recent kernel and JIT symbols |

A common pattern is to run a **Flame Agent** as a DaemonSet that periodically triggers `perf record` for a whitelist of PIDs (discovered via the Kubernetes API). The agent streams raw perf data over gRPC to a **Collapser Service**.

### Processing Layer

The Collapser Service is a small Go microservice:

```go
package main

import (
    "bufio"
    "io"
    "os/exec"
)

func collapsePerf(r io.Reader) (io.Reader, error) {
    cmd := exec.Command("perl", "/usr/local/bin/stackcollapse-perf.pl")
    cmd.Stdin = r
    out, err := cmd.StdoutPipe()
    if err != nil {
        return nil, err
    }
    if err := cmd.Start(); err != nil {
        return nil, err
    }
    return out, nil
}
```

It receives the perf stream, pipes it through `stackcollapse-perf.pl`, and writes the collapsed output to an object store (e.g., Amazon S3). A downstream **Renderer Service** pulls the collapsed file, runs `flamegraph.pl`, and returns a signed URL to the front‑end.

### Storage & Visualization Layer

- **Object Store**: Store `collapsed.txt` and `flamegraph.svg` with a TTL (e.g., 30 days). This keeps storage costs low while preserving history for diff analysis.
- **Dashboard**: Embed the SVG in Grafana using the **Text panel** (set mode to HTML) or a custom React component that fetches the signed URL. Grafana variables can be wired to the CI build number, allowing engineers to switch between versions instantly.
- **Alerting**: Use a simple rule – if the width of any top‑level bar exceeds 20 % of total samples, fire a PagerDuty alert. The alert payload can include a link to the SVG for immediate triage.

#### Diagram (ASCII)

```
+------------+   gRPC   +------------+   S3   +------------+
| FlameAgent |--------->| Collapser  |------->|  Bucket   |
+------------+          +------------+        +------------+
                                   |
                                   | HTTP
                                   v
                            +------------+
                            | Renderer   |
                            +------------+
                                   |
                                   | URL
                                   v
                            +------------+
                            | Grafana UI |
                            +------------+
```

## Patterns in Production: Using Flame Graphs with Specific Languages

### Java – async-profiler

Java’s HotSpot VM emits JIT‑compiled frames that vanilla `perf` cannot resolve. The community standard is **async-profiler**, which integrates with `perf` and produces collapsed stacks directly.

```bash
# Install async-profiler (Linux x86_64)
wget -qO- https://github.com/jvm-profiling-tools/async-profiler/releases/download/v2.9/async-profiler-2.9-linux-x64.tar.gz | tar xz -C /opt
export ASYNC_PROFILER=/opt/async-profiler-2.9-linux-x64

# Record a 30‑second CPU profile for a Java PID
$ASYNC_PROFILER/profiler.sh -d 30 -f /tmp/collapsed.jfr -e cpu -i 99 pid 12345

# Convert JFR to flame graph
$ASYNC_PROFILER/jfr2flamegraph.sh /tmp/collapsed.jfr > /tmp/flamegraph.svg
```

**Pattern:** Run async-profiler as a sidecar that attaches to the main Java container via the shared PID namespace. Store the JFR file in S3, then render on demand. This approach isolates the profiling overhead (usually < 2 %) from the main service.

### Go – pprof + flamegraph.pl

Go ships with built-in pprof HTTP endpoints. Pulling a CPU profile and converting it to a flame graph is straightforward.

```go
// In your Go service (main.go)
import _ "net/http/pprof"

func main() {
    go func() {
        log.Println(http.ListenAndServe(":6060", nil))
    }()
    // ... rest of service ...
}
```

```bash
# Grab a 30‑second profile
curl -s http://localhost:6060/debug/pprof/profile?seconds=30 > cpu.pprof

# Convert to collapsed format (requires go tool)
go tool pprof -raw -seconds 30 cpu.pprof > raw.txt
cat raw.txt | perl /usr/local/bin/stackcollapse-go.pl > collapsed.txt

# Render
perl /usr/local/bin/flamegraph.pl collapsed.txt > flamegraph.svg
```

**Production tip:** Deploy a **sidecar** that periodically curls the `/debug/pprof/profile` endpoint, writes the raw pprof file to a shared volume, and triggers the same collapse/render pipeline described earlier. Because Go’s pprof is lock‑free, the impact on latency is negligible.

### Rust – `perf` + DWARF

Rust binaries produce DWARF debug info when compiled with `-g`. Perf can unwind those frames directly.

```bash
# Build with debug symbols
cargo build --release --features "debug"

# Sample the binary
perf record -F 99 -g -p $(pgrep my_rust_service) -o perf.data -- sleep 30

# Collapse and render
perf script -i perf.data | \
  perl /usr/local/bin/stackcollapse-perf.pl > collapsed.txt
perl /usr/local/bin/flamegraph.pl collapsed.txt > flamegraph.svg
```

**Pattern:** Use a **debug‑symbols sidecar** that mounts the same binary with symbols (e.g., from a `build-artifact` volume) while the production container runs stripped binaries. This lets you keep production images minimal but still generate accurate flame graphs when needed.

## Interpreting the Visuals: Common Pitfalls

1. **Wide Leaf Functions ≠ Root Cause**  
   A leaf that dominates width can be a hot loop, but it may be called from many places. Look *up* the stack to see the common ancestors. If `process_request` appears above 80 % of the width, focus there.

2. **Color Misinterpretation**  
   By default, colors are only aesthetic. However, you can enable `--color=java` to map Java packages to consistent hues, making cross‑run comparison easier.

3. **Sampling Bias**  
   Sampling at too low a frequency can miss short‑lived spikes (e.g., a 5 ms lock). If you suspect high‑frequency latency, increase `-F` to 199 Hz for a short burst.

4. **Missing Symbol Files**  
   A common “[unknown]” bar appears when the binary or library lacks debug symbols. Ensure your CI pipeline retains the `.debug` files or uses `objcopy --only-keep-debug` and `--add-gnu-debuglink`.

5. **JIT Inlining**  
   In Java, aggressive inlining can collapse multiple logical methods into a single native frame, hiding the true hot path. Use async-profiler’s `-e alloc` or `-e lock` events to surface allocation or lock contention instead of pure CPU.

### Quick Checklist Before You Publish a Flame Graph

- [ ] **PID verified** – target process is the one you intend to profile.
- [ ] **Debug symbols available** – `nm -C` shows function names.
- [ ] **Sampling duration** – at least 10 s for steady‑state services, longer for bursty workloads.
- [ ] **Filter noise** – exclude idle threads (`perf record -e cycles:u` restricts to user mode).
- [ ] **Version tag** – embed the service version or Git SHA in the graph title for traceability.

## Key Takeaways

- Flame graphs compress millions of stack samples into a single SVG where **width = time**, making hot paths instantly recognizable.
- A production‑grade pipeline consists of three layers: privileged agents for sampling, stateless collapser/render services, and durable object storage linked to dashboards.
- Language‑specific tooling (async‑profiler for Java, pprof for Go, DWARF + perf for Rust) integrates cleanly with the generic pipeline, preserving a unified workflow.
- Embedding flame graphs in CI/CD enables automatic regression detection via diff graphs, turning performance testing into a visual, code‑review‑friendly artifact.
- Proper symbol management, sampling rates, and color conventions are essential to avoid misinterpretation and to surface hidden latency such as lock contention or GC pauses.

## Further Reading

- [Brendan Gregg’s Flame Graphs page](https://www.brendangregg.com/flamegraphs.html) – the original reference implementation and deep dive into the algorithm.
- [Linux perf documentation](https://www.kernel.org/doc/html/latest/perf.html) – detailed guide to sampling, call‑graph options, and JIT support.
- [Netflix Tech Blog: “Profiling Java at Scale with async-profiler”](https://netflixtechblog.com/profiling-java-at-scale-with-async-profiler-8e4f5b1d9c4c) – production case study and best practices.