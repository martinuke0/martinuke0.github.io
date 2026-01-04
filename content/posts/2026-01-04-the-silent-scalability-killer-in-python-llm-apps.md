---
title: "The Silent Scalability Killer in Python LLM Apps"
date: "2026-01-04T20:15:57.387"
draft: false
tags: ["python", "llm", "concurrency", "scalability", "performance"]
---

Python LLM applications often start small: a FastAPI route, a call to an LLM provider, some prompt engineering, and you're done. Then traffic grows, latencies spike, and your CPUs sit mostly idle while users wait seconds—or tens of seconds—for responses.

What went wrong?

One of the most common and least understood culprits is **thread pool starvation**.

This article explains what thread pool starvation is, why it’s especially dangerous in Python LLM apps, how to detect it, and concrete patterns to avoid or fix it.

---

## 1. What Is Thread Pool Starvation?

### 1.1 The short definition

**Thread pool starvation** happens when:

- You have a **limited pool of worker threads** (a thread pool), and  
- Those threads are **blocked** on long-running or waiting work, so  
- New tasks that need a thread **cannot start**, even though your CPU and event loop look idle.

In other words: you have plenty of work to do and hardware to do it, but your software has run out of “seats” in the only place that’s allowed to do the work.

### 1.2 Why it’s “silent”

Thread pool starvation is a silent scalability killer because:

- CPU usage may be low or moderate.
- Event loop metrics may look fine.
- Network bandwidth may be far from saturated.

Yet:

- Latency increases sharply under load.
- Throughput plateaus far below what you’d expect.
- Tail latencies (p95, p99) become terrible.

From the outside, the app looks “slow but not busy.” From the inside, it’s stuck waiting for threads.

---

## 2. Why Python LLM Apps Are Unusually Vulnerable

Python LLM apps often combine several patterns that make them **especially prone** to thread pool starvation:

1. **Async frameworks everywhere**  
   - FastAPI, Starlette, and other ASGI frameworks are async-first.
   - They rely on `asyncio` and implicitly use **thread pools to run blocking work**.

2. **Sync SDKs inside async routes**  
   - Many LLM SDKs and HTTP libraries are synchronous or are used in synchronous mode.
   - Common pattern: `async def` endpoint → `await loop.run_in_executor(...)` or `asyncio.to_thread(...)` → blocking SDK call inside.

3. **Expensive pre/post-processing**  
   - Chunking, embedding generation, vector DB calls, PDF parsing, diffing, etc.
   - All frequently run **inside the same limited thread pool**.

4. **Streaming and chat UI pressures**  
   - Requests need to stay open while tokens stream back.
   - Developers often run multiple long-lived tasks per request, each grabbing a thread.

5. **Default configuration traps**  
   - `asyncio` default thread pool: relatively small.
   - FastAPI/Starlette sync endpoints run in a (small) worker pool.
   - Many production setups never tune these defaults.

All of this combines into a perfect storm: under light load everything feels fine; under production load, the thread pool saturates and your app “mysteriously” stops scaling.

---

## 3. A Quick Primer: Event Loop vs Thread Pool

Understanding this distinction is essential.

### 3.1 Event loop (async I/O)

In an ASGI app using `asyncio`:

- The **event loop** drives:
  - Socket I/O (HTTP requests, streaming).
  - Timers.
  - High-level async primitives (tasks, futures).
- **No thread** is blocked waiting on I/O; instead, the loop moves between many tasks.

This is what makes async I/O scalable: one thread (or a few) can manage thousands of concurrent requests **if** the work is truly non-blocking.

### 3.2 Thread pool executor

However, not everything is async-friendly. To integrate **blocking** functions with an async app, `asyncio` uses a **thread pool executor**:

- `asyncio.to_thread(func, *args)` or `loop.run_in_executor(executor, func, *args)`  
  submits `func` to a **pool of worker threads**.
- Those threads execute blocking code (`time.sleep`, CPU-bound operations, synchronous HTTP calls, disk I/O, etc.)
- The async task `await`s until the blocking work is done.

Key detail: the thread pool has a **maximum number of worker threads**.

In CPython’s standard `ThreadPoolExecutor`, the default `max_workers` is:

```python
max_workers = min(32, (os.cpu_count() or 1) + 4)
```

So on a 4-core machine, that’s min(32, 4+4) = 8 threads.

If 8 long-running blocking tasks are running at once, the 9th will have to wait until a thread is free.

---

## 4. What Thread Pool Starvation Looks Like in an LLM App

### 4.1 A typical architecture

Imagine a typical Python LLM backend:

- **Framework:** FastAPI with Uvicorn.
- **Routes:** `async def` handlers.
- **LLM calls:** Synchronous SDK (e.g., OpenAI, Anthropic, or a custom HTTP client using `requests`).
- **Extras:** Retrieval from vector DB, embeddings, PDF parsing.

Naïve implementation:

```python
from fastapi import FastAPI
import asyncio
import openai  # sync client (v0.x style)
import requests

app = FastAPI()

async def call_llm(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    # Offload blocking call to thread pool
    return await loop.run_in_executor(
        None,  # None = default executor
        lambda: openai.Completion.create(
            model="gpt-3.5-turbo-instruct",
            prompt=prompt,
            max_tokens=256,
        )["choices"][0]["text"],
    )

async def fetch_context(url: str) -> str:
    loop = asyncio.get_running_loop()
    # Synchronous HTTP call
    return await loop.run_in_executor(
        None,
        lambda: requests.get(url, timeout=10).text,
    )

@app.post("/answer")
async def answer(question: str):
    context = await fetch_context("https://example.com/faq")
    response = await call_llm(f"Q: {question}\nContext: {context}\nA:")
    return {"answer": response}
```

Looks reasonable: blocking work is moved to the thread pool. Under low concurrency, it works.

Under higher concurrency? The cracks appear.

### 4.2 Symptoms under load

When thread pool starvation kicks in, you may see:

- **Latency jumps** as concurrency increases.
  - At 10 concurrent users: 200 ms median.
  - At 50 concurrent users: 1.5 s median, 7 s p95.
  - At 100 concurrent users: requests start timing out.
- **CPU usage remains low** (e.g., 30–40%) despite high latency.
- **Little or no queue visibility**:
  - Logs show requests starting, then nothing for a while, then a burst of completions.
- **Monitoring graphs**:
  - Event loop “busy time” looks okay.
  - But the number of “tasks running in executor” plateaus at a suspicious constant (e.g., 8 or 16).

What’s happening:

1. Each request occupies **one or more threads** in the default thread pool for:
   - `requests.get(...)`
   - `openai.Completion.create(...)`
2. LLM calls and HTTP calls are relatively long-lived (hundreds of ms to many seconds).
3. The maximum number of thread pool workers is quickly reached.
4. New requests must **wait in line** to get a thread before they can even start talking to the LLM or context source.

Your app is “waiting to be allowed to start waiting.”

---

## 5. FastAPI and Sync Endpoints: A Hidden Trap

You might not even use `run_in_executor` explicitly. FastAPI hides a lot of details.

### 5.1 Sync vs async endpoints

In FastAPI:

- `async def endpoint(...)` executes on the event loop.
- `def endpoint(...)` executes in a **worker thread pool**, managed by AnyIO/Starlette.

Example:

```python
from fastapi import FastAPI
import openai  # sync
import requests

app = FastAPI()

@app.post("/chat-sync")
def chat_sync(prompt: str):
    # This entire endpoint runs in a thread pool
    context = requests.get("https://example.com/faq", timeout=10).text
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt + context}],
    )
    return {"answer": response.choices[0].message["content"]}
```

Under the hood, all sync endpoints compete for threads in a **limited pool**. If they all:

- Call a slow LLM API synchronously, and
- Possibly call other blocking services,

you can saturate that pool quickly.

Even if you later convert some parts of the app to `async def`, any remaining sync routes and dependencies will still contend for that same pool.

### 5.2 Mixed sync/async and shared starvation

Common pattern:

- Some routes are `async def`, using `run_in_executor` to call blocking LLM APIs.
- Other routes are `def`, running in FastAPI’s thread pool.
- By default, they often end up sharing a limited number of threads.

Result: a blocking call anywhere can starve unrelated routes.

---

## 6. LLM-Specific Patterns That Cause Starvation

Beyond generic thread pool issues, LLM workloads add their own twists.

### 6.1 Synchronous LLM SDKs in async code

If you are using a **synchronous** client inside async code:

```python
import openai

async def call_llm(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
        ).choices[0].message["content"],
    )
```

Each LLM call pins **one thread** for its entire duration (which can be seconds). With a default pool of 8 or 16 threads, you can hit a very low concurrency ceiling.

### 6.2 Blocking pre/post-processing in the same pool

Codes like:

- Chunking long documents.
- Running synchronous embeddings generation.
- Parsing large PDFs (e.g., `pdfplumber`, `PyPDF2`).
- Running vector DB calls using blocking drivers.

often share the same executor:

```python
async def prepare_context(raw_docs: list[str]) -> list[str]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: expensive_chunking(raw_docs))
```

When all of this runs in the single default executor, you’re effectively serializing major parts of your pipeline under load.

### 6.3 Streaming responses that keep threads busy

Some LLM SDKs or wrappers stream responses in blocking fashion. If you adapt them to async by pushing the whole streaming loop into a thread, you may get:

```python
async def llm_stream(prompt: str):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str] = asyncio.Queue()

    def worker():
        for token in blocking_llm_stream(prompt):
            # Blocking => can stall the worker thread too
            asyncio.run_coroutine_threadsafe(queue.put(token), loop)
        asyncio.run_coroutine_threadsafe(queue.put(None), loop)  # sentinel

    await loop.run_in_executor(None, worker)

    while True:
        token = await queue.get()
        if token is None:
            break
        yield token
```

If each streaming request occupies an executor thread for multiple seconds, you will hit the thread limit quickly.

---

## 7. Detecting Thread Pool Starvation

### 7.1 Observable signals

Look for these patterns in your metrics and logs:

1. **Latency vs concurrency curve**
   - Latency rises slowly at first, then sharply after some concurrency threshold.
   - Throughput plateaus or even drops after that point.

2. **CPU under-utilization**
   - Even under heavy load, CPU < 50–60%.
   - Yet the app behaves as if it’s overloaded.

3. **Fixed cap on concurrent work**
   - Number of concurrent in-flight LLM calls or heavy tasks never exceeds a suspicious constant (often ~8, 16, 32).

4. **Queueing on trivial operations**
   - Logs or traces show long gaps between a request starting and any business logic executing.

### 7.2 Application-level detection

You can explicitly instrument your thread pool usage:

```python
import asyncio
import concurrent.futures
import time
from contextlib import contextmanager

executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

@contextmanager
def timed(label: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        print(f"{label} took {time.perf_counter() - start:.3f}s")

async def monitored_submit(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    with timed("waiting for executor"):
        future = loop.run_in_executor(executor, fn, *args, **kwargs)
        # The "waiting" time here is the queueing delay
    with timed("inside executor"):
        return await future
```

Use this to log:

- Time spent waiting for a thread (`waiting for executor`).
- Time running in a thread (`inside executor`).

If waiting time is significant during load, you are experiencing thread pool contention.

### 7.3 Profiling with traces

If you use distributed tracing (OpenTelemetry, Datadog, etc.):

- Wrap `run_in_executor` or `to_thread` calls with spans.
- Inspect spans for **long queue times** and **limited concurrency**.

You may notice many requests stuck in a “waiting for executor” or “blocked in sync HTTP client” segment.

---

## 8. Fixing the Problem: Design Principles

The core principles to avoid thread pool starvation:

1. **Prefer async end-to-end for I/O-bound work**, especially for:
   - HTTP clients (LLM calls, vector DBs, other microservices).
   - Database drivers (where async variants exist).
2. **Separate CPU-bound and long-blocking work into dedicated pools**:
   - Avoid mixing quick tasks with long-lived ones in a single default pool.
3. **Limit concurrency for truly heavy work**:
   - Use semaphores or rate-limiting to avoid overwhelming shared resources.
4. **Tune pool sizes deliberately**:
   - Don’t rely on small, hidden defaults.

Let’s see how this looks in a Python LLM app.

---

## 9. Moving LLM Calls to Async

### 9.1 Use async-first SDKs where available

Many modern LLM and HTTP SDKs provide async clients. For example, with newer OpenAI Python SDKs (v1.x style) and `httpx`:

```python
from fastapi import FastAPI
from openai import AsyncOpenAI  # async-capable client
import httpx

app = FastAPI()
client = AsyncOpenAI()  # configured via env var OPENAI_API_KEY

@app.post("/answer")
async def answer(question: str):
    async with httpx.AsyncClient() as http_client:
        faq_resp = await http_client.get("https://example.com/faq", timeout=10)
        context = faq_resp.text

    completion = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"Q: {question}\nContext: {context}\nA:"}],
    )

    return {"answer": completion.choices[0].message.content}
```

Benefits:

- No `run_in_executor`.
- No dependence on the thread pool for LLM or HTTP I/O.
- Event loop scales much better with concurrency.

### 9.2 Avoid sync endpoints for async LLM calls

Stick to `async def` endpoints and propagate async to all I/O boundaries. Using sync endpoints with async clients forces internal adaptation that usually re-introduces threads and potential contention.

---

## 10. Isolate and Control Blocking Work

Not everything can be async. Some libraries are purely sync. Some operations are CPU-bound. For those:

### 10.1 Use dedicated executors instead of the default

Instead of dumping everything into the default executor, create explicit executors:

```python
import asyncio
import concurrent.futures

io_bound_executor = concurrent.futures.ThreadPoolExecutor(max_workers=32)
cpu_bound_executor = concurrent.futures.ProcessPoolExecutor(max_workers=4)

async def run_in_io_pool(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(io_bound_executor, func, *args, **kwargs)

async def run_in_cpu_pool(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(cpu_bound_executor, func, *args, **kwargs)
```

You can then:

- Use `io_bound_executor` for blocking network or disk I/O when an async version is unavailable.
- Use `cpu_bound_executor` (or a `ProcessPoolExecutor`) for heavy CPU tasks (e.g., embedding generation in pure Python, PDF parsing).

This avoids CPU-heavy work starving I/O tasks in the same pool (and vice versa).

### 10.2 Apply concurrency limits

When operations are heavy and shared (e.g., a local model, a GPU, or a rate-limited external API), add semaphores:

```python
import asyncio

llm_semaphore = asyncio.Semaphore(16)  # allow up to 16 concurrent LLM calls

async def limited_llm_call(client, **kwargs):
    async with llm_semaphore:
        return await client.chat.completions.create(**kwargs)
```

Instead of letting hundreds of requests simultaneously enqueue blocking LLM calls, you:

- Bound concurrent usage, making performance more predictable.
- Avoid overwhelming your own thread pool or external rate limits.

---

## 11. Handling CPU-Bound Pre/Post-Processing

Many LLM apps do significant local processing:

- Tokenization, chunking, embedding generation.
- Ranking and scoring, summarization of local data.
- Custom evaluation or transformation code.

### 11.1 Keep CPU work off the event loop

Never perform heavy CPU work directly in `async def` without offloading:

```python
def expensive_preprocess(text: str) -> list[str]:
    # Big regex work, chunking, etc.
    ...

async def preprocess_async(text: str) -> list[str]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(cpu_bound_executor, expensive_preprocess, text)
```

### 11.2 Consider processes for CPU-bound work

Because of the GIL, threads do not parallelize CPU-bound Python code well. Use `ProcessPoolExecutor` or external worker processes if CPU work is large and common.

Be careful with:

- Serialization overhead (large objects, big documents).
- Initialization cost (e.g., loading models into memory).

For large, heavy models, a dedicated microservice or worker pattern is often cleaner than `ProcessPoolExecutor` inside your web process.

---

## 12. FastAPI / Uvicorn / Gunicorn Tuning Tips

Thread pool starvation is exacerbated by misconfigured or default server settings.

### 12.1 Uvicorn workers vs threads

Common production deployment pattern:

```bash
gunicorn -k uvicorn.workers.UvicornWorker -w 4 myapp:app
```

Key knobs:

- **Number of workers (`-w 4`)**: OS processes. Each has:
  - Its own event loop.
  - Its own thread pools.
- **Threads per worker (Gunicorn `--threads`)**: only relevant for WSGI workers, not ASGI. For ASGI with UvicornWorker, the main concurrency comes from async tasks and the thread pools used by FastAPI/Starlette/asyncio.

What matters for thread pool starvation:

- The defaults for the **asyncio default executor** and any **FastAPI sync-worker pools**.
- You can:
  - Create your own executors and avoid the default.
  - Configure your own limits via environment variables or app-level initialization.

### 12.2 Don’t treat threads as “free scaling”

If you find yourself simply increasing max workers in thread pools to “fix” latency, you’re buying a little time but not solving the underlying issue.

Risks:

- Too many threads → context-switch overhead, memory bloat, worse latency.
- You still might be bottlenecked by external services (LLM provider rate limits, DB, etc.).

Use more workers and threads judiciously, but pair it with the design fixes:

- Async I/O where possible.
- Separate pools for different kinds of work.
- Concurrency limits.

---

## 13. A Before-and-After Example

Let’s rewrite a toy LLM endpoint to show the difference.

### 13.1 Before: sync SDK + default executor

```python
from fastapi import FastAPI
import asyncio
import openai  # sync v0-style client
import requests

app = FastAPI()

async def get_faq() -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: requests.get("https://example.com/faq", timeout=10).text,
    )

async def ask_llm(question: str, context: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": f"{question}\n\n{context}"}],
        ).choices[0].message["content"],
    )

@app.post("/qa")
async def qa(question: str):
    context = await get_faq()
    answer = await ask_llm(question, context)
    return {"answer": answer}
```

- All expensive work runs in the **default executor**.
- LLM requests take 1–5 seconds each.
- Thread pool saturates with relatively few concurrent users.

### 13.2 After: async SDK + dedicated executor for legacy tasks

```python
from fastapi import FastAPI
from openai import AsyncOpenAI
import httpx
import asyncio
import concurrent.futures

app = FastAPI()
openai_client = AsyncOpenAI()

# Dedicated executor for any unavoidable blocking work
blocking_executor = concurrent.futures.ThreadPoolExecutor(max_workers=32)

async def run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(blocking_executor, func, *args, **kwargs)

@app.post("/qa")
async def qa(question: str):
    # Fully async HTTP request
    async with httpx.AsyncClient() as http_client:
        faq_resp = await http_client.get("https://example.com/faq", timeout=10)
        context = faq_resp.text

    # Fully async LLM call
    completion = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"{question}\n\n{context}"}],
    )

    answer = completion.choices[0].message.content
    return {"answer": answer}
```

Improvements:

- **Zero reliance** on the default executor for core LLM & HTTP I/O.
- **Clear place** (`blocking_executor`) to put any remaining blocking code.
- Scales to far more concurrent requests before hitting any contention.

---

## 14. Checklist: Avoiding Thread Pool Starvation in Python LLM Apps

Use this as a quick audit of your codebase:

1. **Endpoint definitions**
   - [ ] All performance-critical routes are `async def`.
   - [ ] Any `def` endpoints are short and non-blocking or moved to async.

2. **LLM calls**
   - [ ] Using async-capable SDKs where available (`AsyncOpenAI`, `httpx.AsyncClient`, etc.).
   - [ ] No long-lived synchronous LLM calls inside `run_in_executor` without good reason.

3. **HTTP and DB clients**
   - [ ] Prefer async HTTP clients (`httpx.AsyncClient`, `aiohttp`) instead of `requests`.
   - [ ] Use async DB drivers when possible.

4. **Thread pool usage**
   - [ ] Minimal or no use of `asyncio.to_thread` / `run_in_executor` for I/O-bound tasks that could be async.
   - [ ] Dedicated executors for heavy or specialized work, not the default executor.

5. **CPU-bound work**
   - [ ] Offloaded to dedicated process or thread pools.
   - [ ] Protected by concurrency limits when appropriate.

6. **Monitoring**
   - [ ] Metrics or logs that indicate time spent waiting for executor threads.
   - [ ] Load tests that show latency vs concurrency behavior.

7. **Scaling strategy**
   - [ ] Scaling via more workers / instances **plus** design fixes, not just more threads.
   - [ ] Concurrency limits tuned for your LLM provider’s rate limits and your hardware.

---

## 15. Conclusion

Thread pool starvation is a textbook example of a **non-obvious scalability bottleneck**:

- Your Python LLM app might be idle on CPU yet painfully slow.
- The root cause is often a **small, overloaded pool of threads** used to run synchronous work in an otherwise async codebase.
- LLM workloads—long-running calls, streaming, heavy pre/post-processing—magnify the problem.

The cure is not to blindly crank up thread counts, but to:

- Embrace **async I/O end-to-end** where possible.
- **Isolate** blocking and CPU-bound work into dedicated, well-sized executors.
- **Limit** concurrency for heavy shared resources.
- Add **observability** to see when you’re waiting on threads rather than doing useful work.

By recognizing and addressing thread pool starvation, you can unlock the real scalability potential of your Python LLM applications—delivering faster responses to more users without wasting hardware or overprovisioning your infrastructure.