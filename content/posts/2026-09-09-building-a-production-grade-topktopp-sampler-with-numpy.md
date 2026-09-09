

---
title: "Building a Production-Grade Top‑k/Top‑p Sampler with NumPy"
date: "2026-09-09T18:00:50.541"
draft: false
tags: ["numpy", "sampling", "llm", "inference", "performance", "systems"]
description: "Learn to build a high‑performance top‑k/top‑p token sampler with temperature scaling, nucleus selection, and log‑probability tracking using NumPy."
summary: "This tutorial shows how to build a high‑performance top‑k/top‑p token sampler with temperature scaling and per‑token log‑probability tracking using NumPy. It demonstrates real systems skills relevant to ML inference roles."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-09-building-a-production-grade-topktopp-sampler-with-numpy.svg"
  alt: "A conceptual illustration of a token sampling distribution"
  caption: ""
  relative: false
---

> **TL;DR** — In this post you'll implement a NumPy‑based top‑k/top‑p sampler that applies temperature scaling, cumulative‑probability nucleus selection, and multinomial draws while tracking token‑level log‑probabilities. The code is production‑ready, runs on CPU, and can be extended to GPU with minimal changes. It showcases algorithmic efficiency, numerical stability, and systems thinking—attributes that hiring managers look for in senior ML infrastructure roles.

When deploying a language model, the choice of token sampling strategy directly influences output quality, latency, and compute cost. A naive argmax decoder is fast but produces repetitive, boring text, while uncontrolled random sampling can yield incoherent output. The industry standard is a combination of temperature scaling, top‑k filtering, and nucleus (top‑p) sampling, which together provide a tunable trade‑off between diversity and fluency. In this tutorial we will build a self‑contained, NumPy‑only implementation of this pipeline, including per‑token log‑probability tracking, which is essential for downstream tasks such as beam search, reinforcement learning from human feedback (RLHF), and anomaly detection.

## Why This Project Stands Out on a CV

- **Algorithmic depth** – You will implement temperature scaling, cumulative probability masking, and multinomial sampling from scratch, demonstrating a solid grasp of probability theory and numerical linear algebra.
- **Performance engineering** – The solution uses vectorized NumPy operations, avoids Python loops, and can be profiled with tools like `cProfile` or `torch.pro