---
title: "Building a Continuous Batching LLM Serving Engine with Paged KV Cache and Request Preemption"
date: "2026-09-19T01:01:22.485"
draft: false
tags: ["llm-serving", "systems", "python", "cv-project", "performance"]
description: "A hands‑on guide to building a continuous batching LLM serving engine with paged KV cache, token‑level admission control, and request preemption – a portfolio project that signals real‑world systems skill to hiring managers."
summary: "Learn how to design and implement a high‑throughput LLM serving backend that batches requests continuously, uses a paged KV cache for memory efficiency, and preempts low‑priority requests to maximize throughput."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-19-building-a-continuous-batching-llm-serving-engine-with-paged-kv-cache-and-request-preemption.svg"
  alt: "Diagram of a paged KV cache with request preemption"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a continuous batching LLM serving engine from scratch, featuring a paged KV cache, token‑level admission control, and request preemption. By the end you’ll have a runnable Python prototype, a CV‑worthy project, and a clear roadmap to production‑grade features like persistence and horizontal scaling.

## Why This Project Stands Out on a CV

Hiring managers for backend‑infra, ML‑platform, and AI‑product roles look for concrete evidence that you can bridge research prototypes and production systems. This project signals several high‑value competencies:

* **Systems design for latency‑sensitive workloads** – you demonstrate understanding of request‑level scheduling, cache partitioning, and trade‑offs between throughput and latency.
* **Paged data structures** – implementing a paged KV cache mirrors real LLM serving runtimes (e.g., vLLM, TensorRT‑LLM) and shows you can manage memory fragmentation and reuse.
* **Token‑level admission control** – deciding at the token level whether a new request can be admitted teaches you to balance backlog growth vs. service quality, a common interview talking point.
* **Request preemption** – preempting lower‑priority jobs to make room for high‑priority ones is a pattern used in Kubernetes, Airflow, and video‑streaming pipelines; implementing it from scratch shows you can code critical‑path logic.
* **End‑to‑end runnable code** – because the guide produces a working Python prototype, you can point recruiters to a GitHub repo with unit tests, benchmarks, and a quick‑start script, which is far more impressive than a theoretical write‑up.

Roles that particularly value this mix of skills include ML platform engineer, backend infrastructure engineer, and AI systems researcher. The project also provides talking points for interview questions about “how would you improve throughput?” or “describe a time you had to trade off latency for utilization.”

## Architecture Overview

The engine can be visualized as a pipeline of four core components:

```
+---------------------+       +---------------------+       +---------------------+
|   Request Ingestor  | --->  |  Admission Controller| --->  |   Batch Scheduler   |
+---------------------+       +---------------------+       +---------------------+
           |                           |                           |
           v                           v                           v
+---------------------+       +---------------------+       +---------------------+
|   Tokenizer / Embed |       |   Paged KV Cache    |       |   Execution Engine  |
+---------------------+       +---------------------+       +---------------------+

- **Request Ingestor**: a simple async HTTP (or gRPC) endpoint that parses incoming prompts, assigns a priority (default: normal), and enqueues them as *Request objects* containing prompt text, max tokens, and priority flag.
- **Admission Controller**: decides, token‑by‑token, whether a pending request can be admitted into the batch given the current paged cache state. It returns `ADMIT`/`DEFER`/`REJECT`. The logic uses a *token budget* derived from the total cache capacity minus the already‑occupied pages.
- **Paged KV Cache**: each request’s key/value states are stored in fixed‑size pages (e.g., 16 tokens per page). Pages are allocated on‑demand and freed when a request finishes. A free‑page bitmap tracks which pages are occupied, freeing the scheduler to quickly compute admission feasibility.
- **Batch Scheduler**: pulls up to *N* admitted requests, groups them into a continuous batch (no need for all prompts to have the same length). It then dispatches the batch to an execution engine (e.g., a lightweight transformer inference loop or a call to `torch.compile`‑optimized model).
- **Execution Engine**: runs the model forward pass on the batched tokens, producing output logits. After completion, the engine returns the generated tokens to the caller and frees the associated pages.

A text‑style diagram of the data flow:

```
[Client] --> (POST /generate) --> Ingress --> Admission (bitmap) --> Batch Scheduler --> Model (paged KV) --> Response --> [Client]
```

The key insight is that the **Admission Controller** and **Paged KV Cache** work together: the bitmap lets the scheduler know exactly how many tokens can still be accepted, enabling *token‑level* decisions rather than coarse‑grained “accept whole request” checks.

## Building It Step by Step

Below are numbered steps you can follow to produce a functional prototype in Python (≈150 lines of core logic). All code fences include a language tag.

### Step 1 – Project scaffolding

```python
# project/
#   __init__.py
#   server.py       # FastAPI entry point
#   cache.py        # Paged KV cache
#   admission.py    # Token‑level admission control
#   scheduler.py    # Batch scheduler
#   model.py        # Tiny inference stub
```

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn torch numpy
```

### Step 2 – Define the paged KV cache

`cache.py` – the heart of memory efficiency. Pages are 16 tokens wide; the cache size is configurable.

```python
# cache.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

PAGE_SIZE = 16  # tokens per page

@dataclass
class Page:
    id: int                     # unique page identifier
    tokens: List[int] = field(default_factory=lambda: [0] * PAGE_SIZE)  # placeholder token ids
    occupied: bool = False

class PagedKVCache:
    def __init__(self, total_pages: int):
        self.total_pages = total_pages
        self.free_pages: set[int] = set(range(total_pages))
        self.occupied: Dict[int, Page] = {}  # page_id -> Page

    def allocate(self, n_tokens: int) -> List[int]:
        """Allocate enough pages for *n_tokens* and return the list of allocated page ids."""
        needed_pages = (n_tokens + PAGE_SIZE - 1) // PAGE_SIZE
        if len(self.free_pages) < needed_pages:
            raise RuntimeError("Not enough free pages")
        allocated: List[int] = []
        for _ in range(needed_pages):
            pid = self.free_pages.pop()
            self.occupied[pid] = Page(id=pid)
            allocated.append(pid)
        return allocated

    def free(self, page_ids: List[int]) -> None:
        for pid in page_ids:
            self.free_pages.add(pid)
            self.occupied.pop(pid, None)

    def occupancy(self) -> int:
        """Return number of occupied pages."""
        return len(self.occupied)
```

### Step 3 – Token‑level admission control

`admission.py` – decides whether a new request can be admitted based on remaining cache budget.

```python
# admission.py
from .cache import PagedKVCache

MAX_CACHE_PAGES = 256  # tune for your hardware

class AdmissionController:
    def __init__(self, cache: PagedKVCache):
        self.cache = cache

    def try_admit(self, prompt_len: int, max_new_tokens: int, priority: str = "normal") -> str:
        """
        Returns one of: "ADMIT", "DEFER", "REJECT"
        - ADMIT: enough free pages exist.
        - DEFER: free pages exist but would exceed a soft limit (e.g., 80% utilization).
        - REJECT: not enough free pages even if we lower quality.
        """
        needed = (prompt_len + max_new_tokens + PAGE_SIZE - 1) // PAGE_SIZE
        free = self.cache.free_pages.__len__()  # placeholder; we'll compute later
        # Simple budget check:
        utilization = (self.cache.occupation() + needed) / self.cache.total_pages
        if utilization > 0.8 and priority == "low":
            return "DEFER"          # keep low‑priority requests out when we're near capacity
        if the many ways ways. I, s experiences s7. . s. .s. (
 we - - 1.   s
1. 1.  (for example . 
- .  — 1. 

 
 ( 1. 1. 
  1. 
   ( 1.     .  0. 0. 0.   1  (for 0) 0. 0. 0.  (   0.  0.  1  0.  .  .  . .