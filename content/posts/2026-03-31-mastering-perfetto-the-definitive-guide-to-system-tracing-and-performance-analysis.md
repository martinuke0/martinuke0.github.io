---
title: "Mastering Perfetto: The Definitive Guide to System Tracing and Performance Analysis"
date: "2026-03-31T17:29:39.259"
draft: false
tags: ["perfetto","performance tracing","android","system profiling","observability"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [What is Perfetto?](#what-is-perfetto)  
3. [Core Architecture](#core-architecture)  
4. [Setting Up Perfetto](#setting-up-perfetto)  
   - 4.1 [On Android Devices](#on-android-devices)  
   - 4.2 [On Linux Workstations](#on-linux-workstations)  
   - 4.3 [From Chrome and Web Browsers](#from-chrome-and-web-browsers)  
5. [Capturing Traces](#capturing-traces)  
   - 5.1 [Command‑Line Interface (CLI)](#command‑line-interface-cli)  
   - 5.2 [Android Studio Integration](#android-studio-integration)  
   - 5.3 [Perfetto UI (Web UI)](#perfetto-ui-web-ui)  
6. [Analyzing Traces](#analyzing-traces)  
   - 6.1 [Trace Viewer Basics](#trace-viewer-basics)  
   - 6.2 [Common Visualisations](#common-visualisations)  
7. [Advanced Use‑Cases](#advanced-use-cases)  
   - 7.1 [GPU and Frame‑Timeline Tracing](#gpu-and-frame‑timeline-tracing)  
   - 7.2 [Audio, Power, and Thermal Metrics](#audio-power-and-thermal-metrics)  
   - 7.3 [Network and Binder Events](#network-and-binder-events)  
   - 7.4 [Custom Tracepoints & User‑Space Instrumentation](#custom-tracepoints‑user‑space-instrumentation)  
8. [Perfetto vs. Alternatives](#perfetto-vs‑alternatives)  
9. [Performance Impact & Best Practices](#performance-impact‑best-practices)  
10. [Automating Perfetto in CI/CD Pipelines](#automating-perfetto-in-cicd-pipelines)  
11. [Contributing to Perfetto](#contributing-to-perfetto)  
12. [Future Roadmap & Community Vision](#future-roadmap‑community-vision)  
13. [Conclusion](#conclusion)  
14. [Resources](#resources)  

---

## Introduction

Performance engineers, mobile developers, and system observability teams all share a common pain point: **how to get a precise, low‑overhead view of what’s happening inside a complex operating system**. Whether you’re hunting a UI jank on an Android phone, debugging a memory leak in a native library, or trying to understand latency spikes in a micro‑service, you need a tracing framework that can:

* Capture nanosecond‑resolution timestamps across kernel, system‑level, and user‑space components.  
* Correlate events from disparate subsystems (CPU scheduling, GPU rendering, network stack, etc.) into a single, navigable timeline.  
* Export data in a format that can be replayed, queried, and visualised without proprietary lock‑in.  

**Perfetto** is the answer to that need. Born out of Google’s internal tracing infrastructure and open‑sourced in 2019, Perfetto has quickly become the de‑facto standard for system tracing on Android, Chrome, and many Linux‑based platforms. This article is a **comprehensive, in‑depth guide** that will take you from the fundamentals of Perfetto’s design to real‑world, production‑grade usage patterns. By the end, you’ll be able to:

* Install and configure Perfetto on a variety of platforms.  
* Write custom trace configurations and embed tracepoints in your own code.  
* Capture, store, and analyse high‑fidelity traces using the web UI, Android Studio, or programmatic APIs.  
* Integrate Perfetto into automated testing and CI pipelines, while keeping overhead minimal.  

Let’s dive in.

---

## What is Perfetto?

Perfetto is an **open‑source, end‑to‑end tracing system** that unifies three previously separate layers:

| Layer | Description | Typical Use‑Case |
|------|-------------|-----------------|
| **Data Collection** | Low‑overhead kernel and user‑space trace sources (ftrace, atrace, BPF, Android `Trace` API, Chrome tracing). | Capture scheduling, system calls, Binder IPC, GPU frames. |
| **Data Transport & Storage** | A binary protobuf format (`perfetto-trace.proto`) written to a circular buffer or file; optionally streamed over a socket. | Persist traces on device, stream to host for live analysis. |
| **Visualization & Analysis** | Web‑based UI (traceviewer) and IDE integrations (Android Studio, Chrome DevTools). | Slice‑view timelines, flame graphs, stats panels. |

Key attributes that differentiate Perfetto from older tools (e.g., `systrace` or `simpleperf`) include:

* **Unified Data Model** – All events, from kernel `sched_switch` to custom user‑space slices, share the same protobuf schema, making correlation trivial.
* **Zero‑Copy Streaming** – When using the *Perfetto Daemon* (`perfetto` service), data can be streamed directly to a host via ADB without extra buffering.
* **Extensible Trace Configurations** – JSON or protobuf configs let you enable/disable any combination of sources, set buffer sizes, and apply filters.
* **Cross‑Platform Support** – Android, Chrome, Linux (via `perfetto` CLI), and even embedded devices with minimal dependencies.

Perfetto’s official tagline—*“System tracing for Android, Linux and Chrome”*—captures its ambition: a **single, open tracing stack** that works everywhere you need it.

---

## Core Architecture

Understanding Perfetto’s architecture helps you make informed decisions about buffer sizing, source selection, and performance impact. The high‑level flow looks like this:

```
[Trace Sources] → [Perfetto Producer] → [Perfetto Daemon (svc)] → [Trace Buffer] → [Consumer (UI / CLI)] 
```

### 1. Trace Sources (Producers)

* **Kernel Tracers** – `ftrace`, `tracefs`, `bpftrace` (via BPF programs).  
* **Android System Tracers** – `atrace`, `android.os.Trace`, `android.os.Binder` events.  
* **Chrome Tracing** – `trace_event` instrumentation inside Chromium.  
* **Custom User‑Space Producers** – C/C++ `perfetto::TraceWriter`, Java `PerfettoTraceWriter`, Rust bindings, etc.  

Each source registers *track descriptors* (metadata about the thread, process, or subsystem) and streams *trace packets* (the actual events) into the daemon.

### 2. Perfetto Daemon (`perfetto` service)

The daemon runs as a privileged system service (`/system/bin/perfetto`) on Android and as a background process on Linux. Its responsibilities:

* **Multiplexing** multiple producers into a shared circular buffer.  
* **Enforcing Buffer Policies** – e.g., per‑producer quotas, drop‑oldest vs. drop‑newest strategies.  
* **Handling Remote Connections** – ADB port forwarding (`adb forward tcp:9001 localabstract:perfetto`) or TCP sockets for remote streaming.  

The daemon is deliberately lightweight; most of the heavy lifting (packet parsing, UI rendering) happens on the host.

### 3. Trace Buffer

Perfetto stores data in **sharded, fixed‑size buffers** that can be configured per‑producer. The default is a 64 MiB buffer, but production workloads often require 256 MiB or more to capture long‑running scenarios without drops. Buffers are written in a **protobuf varint** format, which yields excellent space efficiency.

### 4. Consumers

* **Web UI (`traceviewer`)** – Hosted at `https://ui.perfetto.dev`. It parses the protobuf stream client‑side and renders an interactive timeline.  
* **Android Studio** – Built‑in *Perfetto* tab for device‑side capture and analysis.  
* **CLI Tools** – `perfetto --txt` for human‑readable dumps, `perfetto --run` for scripted captures.  
* **Programmatic APIs** – The `perfetto::TraceProcessor` library lets you run SQL‑like queries on trace data, enabling automated analysis.

> **Note:** Because the trace format is protobuf‑based, you can also write custom parsers in any language that supports protobuf (Python, Go, Rust, etc.).

---

## Setting Up Perfetto

### 4.1 On Android Devices

Most modern Android devices ship with the Perfetto daemon pre‑installed. To verify:

```bash
$ adb shell ps -A | grep perfetto
root      123   1   5120   1200 S   0:00 /system/bin/perfetto
```

If you’re using a custom ROM or an older device (pre‑Android 10), you may need to manually push the binary:

```bash
# Download the latest perfetto binary from the GitHub release page
$ curl -L -o perfetto https://github.com/google/perfetto/releases/download/v1.0/perfetto-linux-x86_64
$ chmod +x perfetto
$ adb push perfetto /data/local/tmp/
$ adb shell su -c "/data/local/tmp/perfetto --daemonize"
```

> **Tip:** The `--daemonize` flag spawns the service in the background, mimicking the system‑level daemon.

#### Installing the UI Helper (Optional)

Perfetto’s UI can be invoked directly via ADB:

```bash
adb shell "perfetto -c - --txt -o - | curl -X POST -H 'Content-Type: application/octet-stream' --data-binary @- https://ui.perfetto.dev"
```

But for most developers, the web UI at `https://ui.perfetto.dev` is sufficient; you’ll simply upload a `.perfetto-trace` file.

### 4.2 On Linux Workstations

Perfetto can be built from source or installed via package managers (e.g., `apt` on Ubuntu 22.04+). The binary includes both the daemon and the CLI.

```bash
# Install from apt (Ubuntu)
sudo apt update && sudo apt install -y perfetto

# Verify version
perfetto --version
# Output: perfetto 1.2.0
```

On non‑Ubuntu systems, you can download pre‑built releases:

```bash
wget https://github.com/google/perfetto/releases/download/v1.2.0/perfetto-linux-x86_64
chmod +x perfetto-linux-x86_64
sudo mv perfetto-linux-x86_64 /usr/local/bin/perfetto
```

### 4.3 From Chrome and Web Browsers

Chromium‑based browsers expose a **Tracing** endpoint that can be controlled via the Chrome DevTools Protocol (CDP). Perfetto can ingest these traces directly:

```bash
# Start Chrome with remote debugging
google-chrome --remote-debugging-port=9222

# Use CDP to start a trace that Perfetto will consume
curl -X POST http://localhost:9222/json/trace/start -d '{"categories":"*","traceConfig":"{}"}'
# After the scenario finishes:
curl -X POST http://localhost:9222/json/trace/stop -o chrome_trace.json
```

You can then rename `chrome_trace.json` to `chrome_trace.perfetto` and load it in the Perfetto UI.

---

## Capturing Traces

Perfetto offers **multiple capture pathways**: command‑line, IDE integration, and the web UI. Choose the method that aligns with your workflow.

### 5.1 Command‑Line Interface (CLI)

The CLI is the most flexible and scriptable approach. A typical command looks like:

```bash
# Capture a 10‑second trace of CPU scheduling, Binder, and GPU events
perfetto -c - --txt -o /tmp/mytrace.perfetto <<'EOF'
buffers {
  size_kb: 65536  # 64 MiB buffer
}
data_sources {
  config {
    name: "linux.ftrace"
    ftrace_config {
      ftrace_events: "sched_switch"
      ftrace_events: "sched_wakeup"
    }
  }
}
data_sources {
  config {
    name: "android.sysui"
    android_sysui_config {
      enabled: true
    }
  }
}
duration_ms: 10000
EOF
```

**Explanation of the JSON‑like config:**

* `buffers` – defines circular buffer size (default 64 MiB).  
* `data_sources` – each block enables a specific tracer.  
* `ftrace_events` – specify kernel events you care about.  
* `duration_ms` – automatic stop after the given interval.

#### Using a JSON Config File

You can externalise the config to a file (`trace_config.json`) and reference it:

```bash
perfetto -c trace_config.json -o /tmp/trace.perfetto
```

**Sample `trace_config.json`:**

```json
{
  "buffers": [
    { "size_kb": 131072 }   // 128 MiB
  ],
  "data_sources": [
    {
      "config": {
        "name": "android.trace",
        "android_trace_config": {
          "categories": ["gfx", "view", "dalvik"]
        }
      }
    },
    {
      "config": {
        "name": "linux.bpf",
        "bpf_config": {
          "bpf_programs": [
            {
              "name": "sys_enter_openat",
              "bytecode": "AQAB..."
            }
          ]
        }
      }
    }
  ],
  "duration_ms": 5000
}
```

### 5.2 Android Studio Integration

Android Studio (Arctic Fox and newer) has a **Perfetto** tab under *Run > Profiler*. The workflow:

1. Connect device via USB or Wi‑Fi.  
2. Open *Profiler* → *+* → *Perfetto Trace*.  
3. Choose a **pre‑defined configuration** (e.g., *CPU + GPU*, *Network + Binder*) or **custom config** (import the JSON file).  
4. Click **Record** and let the capture run.  
5. The trace appears directly in the Studio UI, with interactive flame‑graphs and per‑process breakdowns.

Studio also supports **record‑on‑trigger** (e.g., start a trace when a specific Activity launches) via the *Advanced Settings* dialog.

### 5.3 Perfetto UI (Web UI)

The web UI is the most powerful visualization tool. To load a trace:

1. Open https://ui.perfetto.dev in a modern browser.  
2. Drag‑and‑drop the `.perfetto` file or click **Open trace**.  
3. Use the *Track Selector* on the left to enable/disable categories.  

The UI provides:

* **Zoomable timeline** with per‑track slicing.  
* **SQL console** (via Trace Processor) for ad‑hoc queries.  
* **Export** options: CSV, JSON, or a trimmed `.perfetto` file.

> **Pro Tip:** You can start a live streaming session by running `adb forward tcp:9001 localabstract:perfetto` and then opening `https://ui.perfetto.dev/?url=ws://localhost:9001`. The UI will receive packets in real time, useful for debugging short‑lived interactions.

---

## Analyzing Traces

### 6.1 Trace Viewer Basics

When you first open a trace, the UI shows a **high‑level overview**:

* **Process Track** – each process gets a collapsible track containing its threads.  
* **CPU Core Tracks** – kernel scheduling events (`sched_switch`) are visualised as colored blocks per core.  
* **GPU Tracks** – frame start/end, composition, and driver events appear under the *GPU* track.  

Hovering over a slice reveals a tooltip with:

* Timestamp (relative and absolute).  
* Duration.  
* Event name and any associated arguments (e.g., `pid=1234, tid=5678`).  

You can right‑click a slice to *Zoom to selection*, *Add to group*, or *Show in Table*.

### 6.2 Common Visualisations

| Visualization | What to Look For | Typical Use‑Case |
|---------------|------------------|------------------|
| **CPU Scheduling (sched_switch)** | Identify thread pre‑emptions, high‑frequency context switches, and CPU core hot‑spots. | Detect UI jank caused by background work stealing CPU from the main thread. |
| **GPU Frame Timeline** | Observe `frame_start` → `frame_end` intervals, and detect *missed vs. presented* frames. | Optimize rendering pipelines, verify vsync adherence. |
| **Binder IPC** | Trace `binder_transaction` events to see inter‑process communication latency. | Debug service‑to‑activity lag, identify heavy system service calls. |
| **Energy & Power** | Use `android.power` tracks (if device supports) to see wake‑locks, CPU frequency changes, and thermal throttling events. | Profile battery impact of background services. |
| **Network Packets** | With `nettrace` enabled, view socket send/receive timestamps. | Correlate network latency with UI state changes. |

#### SQL Query Example

Perfetto’s UI embeds a **SQL console** that runs on the client side using the Trace Processor library. To find the top 5 longest UI thread slices:

```sql
SELECT
  slice.name,
  MAX(slice.duration) AS max_dur,
  slice.thread_name
FROM slice
WHERE slice.thread_name LIKE '%UIThread%'
GROUP BY slice.name
ORDER BY max_dur DESC
LIMIT 5;
```

The result appears as a table, which you can export to CSV for further analysis.

---

## Advanced Use‑Cases

Perfetto’s extensibility shines when you move beyond the out‑of‑box configurations.

### 7.1 GPU and Frame‑Timeline Tracing

On Android, the **GPU driver** (e.g., `adreno`, `mali`) emits events under the `gfx` category. To capture a detailed frame timeline:

```bash
perfetto -c - <<'EOF'
buffers { size_kb: 262144 }   # 256 MiB for long frame captures
data_sources {
  config {
    name: "android.graphics"
    android_graphics_config {
      enabled: true
      trace_gpu_rendering: true
    }
  }
}
duration_ms: 15000
EOF
```

In the UI you’ll see tracks such as:

* `gfx:frame_start` – marks the start of a new frame.  
* `gfx:frame_end` – frame completion (including any compositor work).  
* `gfx:gpu_job` – low‑level GPU command buffer submission.

You can compute **frame latency** by subtracting start from end timestamps. A common metric is **frame time > 16.6 ms** (i.e., > 60 fps), which indicates a dropped frame.

### 7.2 Audio, Power, and Thermal Metrics

Perfetto can ingest **audio latency** events from the `audio` subsystem and **thermal throttling** from `thermal`:

```bash
perfetto -c - <<'EOF'
buffers { size_kb: 65536 }
data_sources {
  config {
    name: "android.audio"
    android_audio_config { enabled: true }
  }
}
data_sources {
  config {
    name: "android.thermal"
    android_thermal_config { enabled: true }
  }
}
duration_ms: 20000
EOF
```

In the UI, the `audio` track will show `audio_output_write` and `audio_input_read` slices, letting you pinpoint gaps that could cause audio glitches.

### 7.3 Network and Binder Events

To capture network stack events, enable the `nettrace` data source (available on Android 12+ and newer Linux kernels with `CONFIG_NET_TRACER`):

```bash
perfetto -c - <<'EOF'
buffers { size_kb: 131072 }
data_sources {
  config {
    name: "android.net"
    android_net_config { enabled: true }
  }
}
duration_ms: 12000
EOF
```

Binder events are already part of `android.sysui` and `android.trace`. You can filter for a specific service:

```sql
SELECT
  ts, dur, name, pid, tid
FROM slice
WHERE name GLOB 'binder_transaction*' AND pid = 1001
ORDER BY ts;
```

### 7.4 Custom Tracepoints & User‑Space Instrumentation

Perfetto provides **C++ and Java APIs** to emit custom slices from your own code. Here’s a minimal C++ example:

```cpp
#include <perfetto.h>

PERFETTO_DEFINE_CATEGORIES(
    perfetto::Category("myapp").SetDescription("MyApp custom events"));

int main() {
  // Initialize Perfetto tracing for the process.
  perfetto::TracingInitArgs args;
  args.backends = perfetto::BackendType::IN_PROCESS; // No daemon needed for small apps
  perfetto::Tracer::Initialize(args);

  // Create a trace writer for the default data source.
  auto* writer = perfetto::TrackEvent::GetTraceWriter();

  // Emit a slice.
  TRACE_EVENT_BEGIN("myapp", "LoadResources");
  // ... do work ...
  TRACE_EVENT_END("myapp");

  // Flush and stop.
  writer->Flush();
  perfetto::Tracing::Flush();
  return 0;
}
```

In Java (Android):

```java
import android.os.Trace;
import android.perfetto.PerfettoTraceWriter;
import android.perfetto.TraceEvent;

public class MyActivity extends Activity {
    private PerfettoTraceWriter writer = PerfettoTraceWriter.getInstance();

    void loadData() {
        Trace.beginSection("loadData"); // Legacy API, also appears in Perfetto
        TraceEvent.begin("myapp", "LoadData");
        // ... heavy work ...
        TraceEvent.end("myapp", "LoadData");
        Trace.endSection();
    }
}
```

**Key points:**

* **Categories** help you filter in the UI (`myapp`).  
* **TraceWriter** can be shared across threads, allowing per‑thread slices.  
* **Batched writes** reduce overhead; you can call `writer->Flush()` at strategic points (e.g., after a frame).

#### Using BPF for Kernel‑Space Custom Events

Perfetto can ingest **BPF programs** that emit custom trace packets. Example (BPF program compiled with `clang`):

```c
#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>
#include <perfetto.h>

SEC("tracepoint/syscalls/sys_enter_openat")
int trace_openat(struct trace_event_raw_sys_enter *ctx) {
    struct perfetto_event ev = {};
    ev.type = PERFETTO_EVENT_TYPE_STRING;
    ev.string_value = "openat_enter";
    perfetto_write(&ev);
    return 0;
}
char _license[] SEC("license") = "GPL";
```

After loading the BPF program via `perfetto --bpf myprog.o`, the custom events appear under a *BPF* track.

---

## Perfetto vs. Alternatives

| Feature | Perfetto | Systrace | simpleperf | ftrace (raw) |
|---------|----------|----------|------------|--------------|
| **Unified UI** | ✅ (Web UI, Android Studio) | ❌ (CLI only) | ❌ (CLI only) | ❌ |
| **Cross‑Platform** | Android, Chrome, Linux | Android only | Android only | Linux only |
| **Custom User‑Space API** | ✅ (C++, Java, Rust) | ❌ | ❌ | ❌ |
| **Zero‑Copy Streaming** | ✅ (ADB forward) | ❌ | ❌ | ❌ |
| **SQL Query Engine** | ✅ (TraceProcessor) | ❌ | ❌ | ❌ |
| **Low Overhead** | ~1 µs per event | ~2–3 µs | ~5 µs (sampling) | Varies |
| **Buffer Management** | Configurable circular buffers | Fixed size | Fixed size | Fixed size |
| **Community & Docs** | Active GitHub, Google docs | Legacy docs | Limited | Kernel docs |

**When to choose Perfetto:**  
* When you need **full‑stack visibility** (kernel + system services + app).  
* When you want to **automate** trace collection in CI pipelines.  
* When you require **SQL querying** for systematic regression detection.

**When a simpler tool may suffice:**  
* Quick one‑off CPU sampling (`simpleperf`) for a single process.  
* Minimalistic tracing on older devices that lack the Perfetto daemon.

---

## Performance Impact & Best Practices

Even though Perfetto is designed for low overhead, careless configuration can still affect the device under test.

| Pitfall | Symptom | Mitigation |
|---------|---------|------------|
| **Oversized Buffers** | Memory pressure, OOM kills on low‑RAM devices. | Use the smallest buffer that still captures the required window; enable *drop_oldest* policy if needed. |
| **Too Many Event Types** | High CPU usage in the daemon, dropped events. | Enable only the categories you need (`sched_switch`, `binder_transaction`, `gfx`). |
| **High‑Frequency Custom Slices** | 10k+ slices per second can saturate the trace pipe. | Batch custom events, or use *tracepoint* (kernel) instead of per‑slice. |
| **Streaming Over ADB** | Limited bandwidth may cause backpressure. | Use `adb forward` with `--no-streaming` for short captures, or pull the file after capture for longer runs. |
| **Running on Production Devices** | Unexpected latency spikes for end‑users. | Use **sampling mode** (`perfetto --trace-config=sampled`) or enable only *lightweight* sources (e.g., `android.log`). |

### Recommended Baseline Config for UI Performance Audits

```json
{
  "buffers": [{ "size_kb": 131072 }],   // 128 MiB
  "data_sources": [
    { "config": { "name": "android.trace", "android_trace_config": { "categories": ["gfx", "view", "dalvik"] } } },
    { "config": { "name": "linux.ftrace", "ftrace_config": { "ftrace_events": ["sched_switch", "sched_wakeup"] } } },
    { "config": { "name": "android.binder", "android_binder_config": { "enabled": true } } }
  ],
  "duration_ms": 15000
}
```

This captures the essential UI pipeline while staying comfortably under 5 % CPU overhead on most flagship devices.

---

## Automating Perfetto in CI/CD Pipelines

Performance regressions often surface only under load. Embedding Perfetto in a **continuous integration** workflow can catch them early.

### Example: GitHub Actions Workflow

```yaml
name: Perfetto Performance Test

on:
  pull_request:
    branches: [ main ]

jobs:
  trace:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v3

      - name: Install Perfetto
        run: |
          sudo apt-get update
          sudo apt-get install -y perfetto

      - name: Start Android emulator
        uses: reactivecircus/android-emulator-runner@v2
        with:
          api-level: 33
          target: aosp_arm64
          arch: arm64
          script: |
            adb devices

      - name: Run Instrumented UI Test with Perfetto
        run: |
          # Push the test APK and run instrumentation
          adb install -r app-debug.apk
          # Start a Perfetto trace in the background
          perfetto -c perfetto_ui_test.cfg -o /tmp/trace.perfetto &
          TRACE_PID=$!
          # Run the UI test (Espresso, UIAutomator, etc.)
          adb shell am instrument -w -r -e debug false com.example.test/androidx.test.runner.AndroidJUnitRunner
          # Stop tracing
          kill $TRACE_PID
          # Pull trace to the runner
          adb pull /tmp/trace.perfetto ./trace.perfetto

      - name: Analyse trace for frame drops
        run: |
          # Use the TraceProcessor CLI to query frame times
          trace_processor --query "SELECT MAX(dur) FROM slice WHERE name='gfx:frame_end'" trace.perfetto > frame_stats.txt
          cat frame_stats.txt
          # Fail if any frame exceeds 20ms
          if awk '$1 > 20000000 {exit 1}' frame_stats.txt; then
            echo "Performance regression detected!"
            exit 1
          fi
```

**Key takeaways:**

* **Config File (`perfetto_ui_test.cfg`)** contains a focused set of sources to keep CI runtimes low.  
* The trace is captured **in the background** while the UI test runs, ensuring minimal interference.  
* `trace_processor` provides a **SQL‑based gate** that can fail the CI job automatically if thresholds are breached.

You can extend this pattern to **benchmark suites**, **benchmark-as-a-service** platforms, or **nightly performance dashboards**.

---

## Contributing to Perfetto

Perfetto is a community‑driven project under the Apache 2.0 license. If you want to give back:

1. **Fork the Repository** – https://github.com/google/perfetto  
2. **Set Up the Build Environment** – Follow the `README.md` for Bazel or CMake.  
   ```bash
   sudo apt-get install -y bazel
   git clone https://github.com/google/perfetto.git
   cd perfetto
   bazel build //tools/perfetto:perfetto
   ```
3. **Pick an Issue** – Good first‑timers are labelled *“good first issue”*.  
4. **Write Tests** – Perfetto relies heavily on integration tests that run on the host and device.  
5. **Submit a Pull Request** – Follow the contribution guidelines (sign the CLA, include a *Change‑Log* entry).  

Perfetto also has a **monthly community call** (Google Meet) where contributors discuss roadmap items, performance regressions, and upcoming features. The call recordings are posted on the project's YouTube channel.

---

## Future Roadmap & Community Vision

The Perfetto team has outlined several **high‑impact directions** for the next 12–24 months:

| Roadmap Item | Description | Expected Impact |
|--------------|-------------|-----------------|
| **Native WebAssembly Tracing** | Enable tracing of WebAssembly modules in Chrome and Edge. | Better visibility into WASM‑heavy web apps. |
| **Distributed Tracing Integration** | Export Perfetto traces to OpenTelemetry back‑ends (Jaeger, Zipkin). | Seamless correlation across device and server side. |
| **AI‑Assisted Anomaly Detection** | Built‑in machine‑learning models that flag outlier slices. | Early detection of performance regressions without manual queries. |
| **Low‑Power Embedded Mode** | A stripped‑down daemon for IoT devices (< 64 MiB RAM). | Expand Perfetto’s reach to automotive and wearables. |
| **Improved UI Editing** | Drag‑and‑drop slice editing and annotation directly in the web UI. | Faster root‑cause analysis and sharing of findings. |

The roadmap is **community‑driven**; developers can vote on features via the GitHub issue tracker. Keeping an eye on the project’s *roadmap.md* file is recommended for anyone building long‑term tooling around Perfetto.

---

## Conclusion

Perfetto has matured from an internal Google tracing system into a **robust, cross‑platform observability stack** that empowers developers to see, understand, and improve the performance of modern Android, Chrome, and Linux applications. By mastering its architecture, configuration language, and analysis tools, you can:

* Capture **nanosecond‑resolution** system‑wide traces without crippling the device.  
* Correlate **CPU, GPU, Binder, Network, Power, and custom** events in a single timeline.  
* Automate **regression detection** in CI pipelines, dramatically reducing the time to spot performance bugs.  
* Extend the tracing ecosystem with **custom user‑space events** and **BPF‑based kernel probes**.  

Whether you are a mobile app engineer chasing the last few milliseconds of UI smoothness, a kernel developer debugging scheduling anomalies, or a site reliability engineer correlating front‑end latency with back‑end services, Perfetto gives you the **single source of truth** you need. With an active community, a clear roadmap, and the backing of Google’s performance teams, Perfetto is poised to remain the cornerstone of system tracing for years to come.

Happy tracing!

---

## Resources

1. **Perfetto Official Documentation** – Comprehensive guides, API references, and best‑practice articles.  
   <https://perfetto.dev/docs>

2. **GitHub Repository** – Source code, issue tracker, and contribution guidelines.  
   <https://github.com/google/perfetto>

3. **Trace Processor SQL Reference** – Detailed description of the SQL dialect used in the UI console.  
   <https://perfetto.dev/docs/analysis/sql>

4. **Android Developers – Perfetto Integration** – Official Android blog post on using Perfetto for app performance.  
   <https://developer.android.com/topic/performance/tracing/perfetto>

5. **Chrome DevTools Protocol – Tracing** – How to capture Chrome traces compatible with Perfetto.  
   <https://chromedevtools.github.io/devtools-protocol/tot/Tracing/>

---