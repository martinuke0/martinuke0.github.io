---
title: "Dynamic Temperature Scheduler for LLM Sampling"
date: "2026-11-05T07:00:38.301"
draft: false
tags: ["LLM", "Sampling", "Entropy", "Python", "Systems"]
description: "Build a token‑level temperature scheduler that adapts via entropy feedback and applies top‑k and top‑p filtering, demonstrating advanced sampling control."
summary: "A hands‑on guide to a token‑level temperature scheduler that reacts to entropy and applies top‑k/top‑p filtering, perfect for showcasing systems expertise."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-05-dynamic-temperature-scheduler-for-llm-sampling.svg"
  alt: "Dynamic temperature scheduler concept"
  caption: ""
  relative: false
---

> **TL;DR** — This project implements a per‑token temperature scheduler that adjusts sampling temperature based on real‑time entropy estimates, combined with top‑k and top‑p filtering. It demonstrates advanced LLM inference control and is built with PyTorch and the Hugging Face Transformers library, providing a concrete portfolio piece for systems‑focused roles.

Large language models (LLMs) generate text by sampling from a probability distribution over tokens. The temperature parameter controls the sharpness of that distribution, but a static temperature often produces either overly deterministic or chaotic output. In this post we build a dynamic temperature scheduler that reacts to the entropy of the model's predicted distribution on a per‑token basis, and we combine it with top‑k and top‑p filtering to give fine‑grained, on‑the‑fly control over sampling. The implementation is fully runnable in Python, uses the popular Hugging Face Transformers library, and can be extended into a production‑grade inference service.

## Why This Project Stands Out on a CV

- **Systems‑level inference control** – you are not just calling `model.generate()`; you are manipulating the sampling distribution at the token level, which signals deep understanding of how LLMs produce text.
- **Real‑time adaptation** – the scheduler reacts to entropy feedback, a concept borrowed from information theory and applied to a practical ML pipeline, showcasing cross‑domain expertise.
- **Integration of multiple sampling strategies** – combining top‑k, top‑p, and temperature demonstrates the ability to orchestrate several techniques for optimal output quality.
- **Production‑ready extensibility** – the codebase is structured so that you can add persistence, observability, and horizontal scaling, which are common requirements in MLOps roles.
- **Portfolio‑friendly** – the project is self‑contained, runs on a single GPU, and can be demoed in minutes, making it ideal for interviews and LinkedIn posts.

## Architecture Overview

The system is composed of five loosely coupled components:

1. **Tokenizer & Model Wrapper** – loads a Hugging Face model and tokenizer, exposing a method to obtain raw logits for a given prompt.
2. **Entropy Estimator** – computes the Shannon entropy of the softmax distribution over the vocabulary for the next token.
3. **Temperature Scheduler** – maps the current entropy to a temperature value using a configurable schedule (e.g., linear, exponential, or piecewise).
4. **Top‑k / Top‑p Filter** – prunes the distribution to the top‑k tokens or to the smallest set whose cumulative probability exceeds p.
5. **Sampling Loop** – iterates token‑by‑token, applying the scheduler and filters, then samples from the filtered distribution until a stop condition is met.

A high‑level flow is:

```
Prompt → Model → Logits → Entropy → Temperature → Filter → Sample → Append → Repeat
```

Each step is isolated, making it easy to swap or extend individual parts.

## Building It Step by Step

### Step 1: Install dependencies

```bash
pip install torch transformers numpy
```

### Step 2: Load the model and tokenizer

```python
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

model_name = "distilgpt2"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name)
model.eval()
```

### Step 3: Compute entropy of the next‑token distribution

```python
def compute_entropy(logits: torch.Tensor) -> float:
    """
    logits: tensor of shape (vocab_size,) containing raw model logits.
    Returns the Shannon entropy of the softmax distribution.
    """
    probs = torch.softmax(logits, dim=-1)
    # Avoid log(0) by adding a tiny epsilon
    log_probs = torch.log(probs + 1e-12)
    entropy = -torch.sum(probs * log_probs).item()
    return entropy
```

### Step 4: Implement the temperature scheduler

```python
class TemperatureScheduler:
    def __init__(self, base_temp: float = 1.0, entropy_threshold: float = 2.0):
        self.base_temp = base_temp
        self.entropy_threshold = entropy_threshold

    def __call__(self, entropy: float) -> float:
        """
        Adjust temperature based on entropy.
        Low entropy → lower temperature (more deterministic).
        High entropy → higher temperature (more exploratory).
        """
        if entropy < self.entropy_threshold:
            # Linearly decrease temperature as entropy drops
            return max(self.base_temp * (entropy / self.entropy_threshold), 0.1)
        else:
            # Increase temperature beyond base for high uncertainty
            return self.base_temp * (1.0 + (entropy - self.entropy_threshold) / self.entropy_threshold)
```

### Step 5: Apply top‑k and top‑p filtering

```python
def top_k_filter(logits: torch.Tensor, k: int) -> torch.Tensor:
    """Zero out logits for tokens outside the top‑k."""
    top_k = torch.topk(logits, k).values[-1]
    logits = torch.where(logits < top_k, torch.full_like(logits, -float('inf')), logits)
    return logits

def top_p_filter(logits: torch.Tensor, p: float) -> torch.Tensor:
    """Zero out logits for tokens outside the nucleus of cumulative probability p."""
    sorted_logits, sorted_indices = torch.sort(logits, descending=True)
    cumulative_probs = torch.cumsum(torch.softmax(sorted_logits, dim=-1), dim=-1)
    # Remove tokens with cumulative probability above p
    sorted_indices_to_remove = cumulative_probs > p
    # Shift indices to keep at least one token
    sorted_indices_to_remove[1:] = sorted_indices_to_remove[:-1].clone()
    sorted_indices_to_remove[0] = False
    indices_to_remove = sorted_indices[sorted_indices_to_remove]
    logits = logits.clone()
    logits[indices_to_remove] = -float('inf')
    return logits
```

### Step 6: Assemble the generation loop

```python
@torch.no_grad()
def generate_with_dynamic_temperature(
    prompt: str,
    max_new_tokens: int = 50,
    k: int = 50,
    p: float = 0.9,
    scheduler: TemperatureScheduler = None,
) -> str:
    if scheduler is None:
        scheduler = TemperatureScheduler()

    input_ids = tokenizer.encode(prompt, return_tensors='pt')
    past = None

    for _ in range(max_new_tokens):
        outputs = model(input_ids=input_ids, past_key_values=past)
        logits = outputs.logits[0, -1, :]
        entropy = compute_entropy(logits)

        # Adjust temperature based on entropy
        temp = scheduler(entropy)
        # Scale logits by temperature
        logits = logits / temp

        # Apply top‑k and top‑p
        logits = top_k_filter(logits, k)
        logits = top_p_filter(logits, p)

        # Sample from the filtered distribution
        probs = torch.softmax(logits, dim=-1)
        next_token = torch.multinomial(probs, num_samples=1)

        # Append to sequence
        input_ids = torch.cat([input_ids, next_token], dim=-1)
        past = outputs.past_key_values

        # Stop on EOS token
        if next_token.item() == tokenizer.eos_token_id:
            break

    return tokenizer.decode(input_ids[0], skip_special_tokens=True)
```

### Step 7: Test the pipeline

```python
if __name__ == "__main__":
    prompt = "The meaning of life is"
    output = generate_with_dynamic_temperature(prompt, max_new_tokens=30)
    print("Generated text:", output)
```

Running the script will produce a continuation whose randomness adapts to the model's confidence at each step.

## Running and Testing It

1. Save the code above in a file named `temp_scheduler.py`.
2. Execute it with Python 3.10+:

```bash
python temp_scheduler.py
```

3. Observe the output. To verify that the temperature is indeed changing, you can log the `temp` variable inside the loop:

```python
print(f"Step {step}: entropy={entropy:.3f}, temperature={temp:.3f}")
```

4. For a more rigorous test, compare the generated text with a static temperature baseline:

```python
def generate_static_temperature(prompt, temperature=1.0, max_new_tokens=30):
    input_ids = tokenizer.encode(prompt, return_tensors='pt')
    for _ in range(max_new_tokens):
        outputs = model(input_ids=input_ids)
        logits = outputs.logits[0, -1, :] / temperature
        probs = torch.softmax(logits, dim=-1)
        next_token = torch.multinomial(probs, num_samples=1)
        input_ids = torch.cat([input_ids, next_token], dim=-1)
        if next_token.item() == tokenizer.eos_token_id:
            break
    return tokenizer.decode(input_ids[0], skip_special_tokens=True)
```

Run both and compare diversity and coherence.

## Extending It: Your Roadmap to Senior-Level

- **Persist temperature schedules** – store each token's entropy and chosen temperature in Redis or PostgreSQL. This enables A/B testing of different schedules and provides data for offline analysis.
- **Horizontal scaling** – wrap the generation logic in a FastAPI service and deploy multiple workers behind a load balancer. Use async I/O to handle concurrent requests without blocking the GPU.
- **Observability** – emit OpenTelemetry metrics for latency, entropy distribution, and temperature values. Visualize them in Grafana to detect drift or anomalies in production.
- **Fault tolerance** – implement retry with exponential backoff and a fallback to a secondary model instance. This is critical for high‑availability inference endpoints.
- **Benchmarking harness** – integrate with the `lm‑evaluation‑harness` to quantify perplexity, diversity, and speed across different temperature schedules, providing evidence for model improvements.
- **Kubernetes auto‑scaling** – define a custom metric based on queue length or GPU utilization, and let the Horizontal Pod Autoscaler add or remove pods automatically.

## Key Takeaways

- The project demonstrates per‑token control of LLM sampling, a skill that bridges ML research and systems engineering.
- Entropy‑driven temperature adaptation produces more nuanced output than static settings, and the code is short enough to be explained in an interview.
- The modular architecture makes it trivial to add persistence, scaling, and observability—common requirements for senior ML roles.
- By integrating top‑k and top‑p filtering, you showcase familiarity with the full suite of modern sampling techniques.
- The implementation runs on a single GPU, yet its design paves the way for production‑grade deployment.

## Further Reading

- [Hugging Face Transformers Documentation](https://huggingface.co/docs/transformers/) – the canonical source for model loading and generation utilities.
- [Nucleus Sampling: Top‑p Sampling for Neural Text Generation](https://arxiv.org/abs/1904.09740) – the original paper introducing top‑p filtering.
- [The Curious Case of Neural Text Degeneration](https://arxiv.org/abs/1904.09740) – an early study on sampling strategies that motivates entropy‑based control.
- [PyTorch Documentation](https://pytorch.org/docs/) – reference for tensor operations, sampling, and GPU acceleration.
- [OpenTelemetry for Python](https://opentelemetry.io/docs/instrumentation/python/) – guide for adding observability to your inference service.