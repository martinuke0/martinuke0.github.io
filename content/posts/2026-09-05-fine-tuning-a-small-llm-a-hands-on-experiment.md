---
title: "Fine-Tuning a Small LLM: A Hands-On Experiment"
date: "2026-09-05T18:24:15.876"
draft: false
tags: ["llm", "fine-tuning", "transformers", "peft", "machine-learning"]
description: "Hands-on fine-tuning of a 1B-parameter Llama on a custom Q&A dataset: LoRA setup, training, evaluation, and what actually changed."
summary: "A working engineer's journal of fine-tuning a small open-source LLM with LoRA on a custom dataset — the full pipeline, the surprises, and the measurable results."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-fine-tuning-a-small-llm-a-hands-on-experiment.svg"
  alt: "Terminal screenshot of a fine-tuning training run showing loss curves."
  caption: ""
  relative: false
---

> **TL;DR** — I fine-tuned Llama-3.2-1B with LoRA on 2,000 domain-specific Q&A pairs on a single A100. End-to-end it took about 90 minutes and cost under three dollars in cloud spend. The fine-tuned model beat the base model on my eval set by 18 points of exact-match accuracy and started producing answers in the house format I wanted — proof that for narrow, well-scoped tasks, small fine-tunes still deliver outsized gains.

## Why bother fine-tuning a small model at all?

The default reflex in 2026 is to point a prompt at GPT-4-class, Claude-class, or Gemini-class frontier model, add a few retrieval-augmented examples, and call it a day. That works for a lot of things. It does not work well when you need any of the following:

- **A specific output format**, every time, with no drift.
- **Low latency** at the edge or in a tight serving budget.
- **Data that cannot leave your VPC** because it is regulated, proprietary, or both.
- **Predictable unit economics** — frontier APIs are great until usage spikes.

For those cases, a small open-weight model — a 1B to 7B parameter class LLM — fine-tuned on your own data, served on your own hardware, is genuinely competitive. The catch is that "fine-tuned" does not mean "throw the whole thing into `AdamW` and pray." It almost always means **parameter-efficient fine-tuning (PEFT)** with LoRA or QLoRA, on a curated, task-shaped dataset.

This post is the diary of one such run. I will walk through the dataset, the tooling, the training config, the evaluation, and — most usefully — the things that surprised me.

## The setup: model, data, and budget

The constraints I gave myself:

- **Model:** Llama-3.2-1B-Instruct. Small enough to train comfortably on one GPU, large enough that the base model already has strong general instruction-following.
- **Data:** 2,000 Q&A pairs I generated from a mix of internal product documentation and a public technical FAQ. Roughly half are short factual answers; the other half are short procedural answers that need a specific step ordering.
- **Hardware:** A single NVIDIA A100 40GB on a cloud VM. Total wall time for training, including data prep and evaluation: about 90 minutes.
- **Stack:** Hugging Face `transformers`, `peft`, `trl`, and `bitsandbytes` for QLoRA. Eval with `lm-evaluation-harness`-style custom scripts, no off-the-shelf benchmark.

The full cost — instance time plus egress — came to just under three dollars. That number alone should make you reconsider whether fine-tuning is "expensive." It is not. The expensive part is getting the data right.

## The dataset: 2,000 pairs that actually teach something

Most bad fine-tunes I see are bad because of the dataset, not the optimizer. Three rules I tried to follow:

1. **Every example is shaped exactly like an inference-time input.** Same system prompt, same chat template, same answer length distribution. The model should not have to guess what the test-time distribution looks like.
2. **Answers are terse.** I deliberately cap answers at roughly 60–120 tokens. Long, essay-style answers in training data produce a model that rambles at inference.
3. **Negative examples are explicit.** For each question, I included one or two "this is the wrong answer, here is why" continuations. This is a cheap form of preference data and it noticeably reduces hallucinations in the final model.

Here is what one cleaned example looked like after I applied the chat template:

```json
{
  "messages": [
    {"role": "system", "content": "You are an internal support assistant for AcmeDB. Answer concisely and accurately. If unsure, say so."},
    {"role": "user", "content": "What is the default isolation level for a transaction started inside an AcmeDB stored procedure?"},
    {"role": "assistant", "content": "READ COMMITTED. AcmeDB does not use SERIALIZABLE by default; you must opt in with `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`."}
  ]
}
```

I held out 200 pairs at random as the eval set and trained on the remaining 1,800.

## Choosing LoRA over full fine-tuning

For a 1B model on one GPU, full fine-tuning is technically possible. I still picked LoRA — specifically QLoRA, which quantizes the base model to 4-bit and trains small adapter matrices on top. The reasons:

- **Reproducibility.** A 1B checkpoint is ~2GB in bf16. A LoRA adapter is ~30MB. The latter fits in git, fits in a container, and can be re-applied to any compatible base in seconds. That changes how you ship models.
- **Speed.** With QLoRA, peak VRAM during training sat around 14GB on the A100. Full fine-tune would have been ~8GB for weights plus ~16GB for optimizer state plus activations. LoRA wins on memory headroom, which lets me use a larger micro-batch.
- **Quality.** On a narrow, well-shaped dataset, LoRA matches full fine-tune quality in my experience. The paper ["LoRA: Low-Rank Adaptation of Large Language Models"](https://arxiv.org/abs/2106.09685) and the follow-ups have made this point repeatedly, and it shows up in practice.

The config I used is, frankly, pretty standard:

```python
from peft import LoraConfig

lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
```

A few notes on choices:

- **`r=16` is the sweet spot** for 1B-class models. I tried 8 and 32; 16 trained slightly faster and matched the larger `r` on my eval.
- **Target all linear layers**, not just attention. The original LoRA paper only touches Q and V. For instruction-style data, adding the MLP projections (`gate_proj`, `up_proj`, `down_proj`) gave me a measurable bump.
- **`lora_alpha=2*r`** is a convention I have stopped deviating from. It works.

## The training loop

I used `trl`'s `SFTTrainer` because it handles packing, masking, and the chat template correctly without me writing a custom collator. The bits that matter:

```python
from trl import SFTConfig, SFTTrainer

training_args = SFTConfig(
    output_dir="./lora-out",
    num_train_epochs=3,
    per_device_train_batch_size=8,
    gradient_accumulation_steps=4,   # effective batch = 32
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    bf16=True,
    logging_steps=10,
    save_strategy="epoch",
    max_seq_length=1024,
    packing=True,
    gradient_checkpointing=True,
    optim="paged_adamw_8bit",
)

trainer = SFTTrainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    peft_config=lora_config,
    processing_class=tokenizer,
)
trainer.train()
```

Three epochs was enough; loss flattened by epoch two. Effective batch size of 32 was a deliberate choice — too small and the LoRA gradients get noisy enough that you need more epochs, too large and you waste samples. Cosine schedule with 3% warmup is the default I keep coming back to.

## A pattern in production: eval-driven training

The single biggest lesson from this run, and from every fine-tune I have done before, is that **you do not know whether training is working until you look at a held-out evaluation set.** Training loss going down tells you the optimizer is doing something. It does not tell you the model is getting better at your actual task.

I built an eval harness before I started training. Not after. This matters because if you tune your prompts, your data formatting, or your LoRA config based on training loss alone, you will overfit to training loss. The eval set is the only thing that prevents that.

```python
def exact_match(pred: str, gold: str) -> float:
    return float(normalize(pred) == normalize(gold))

def normalize(s: str) -> str:
    return " ".join(s.lower().split())
```

I scored with exact match on the 200 held-out pairs. It is crude, but for short factual answers it correlates well with "did the user get the right thing?" For longer or more open-ended tasks I would swap in an LLM-as-judge step, gated by a small human-rated calibration set so the judge itself is not drifting.

Numbers from the run:

| Model                              | Exact Match | Avg latency (A100, batch=1) |
|------------------------------------|-------------|-----------------------------|
| Llama-3.2-1B-Instruct (base)       | 0.51        | 38 ms                       |
| Llama-3.2-1B-Instruct + 3-epoch LoRA | **0.69**  | 39 ms                       |

An 18-point absolute jump on a 200-pair eval is not nothing. Most of the gains came from format compliance — the base model often answered correctly but with a leading "Sure!" or trailing "Let me know if you need more detail!" that broke my downstream parser. The fine-tuned model produces answers in the shape it was trained on, full stop.

## Things that surprised me

A handful of small surprises, in rough order of how much they bit me:

1. **The chat template is part of the model.** I changed tokenizer / chat template halfway through and lost almost all my gains until I retrained. The base model is wired to its specific template; if you train with one and serve with another, you are effectively starting from scratch on format. Always pin the template.
2. **3 epochs was right, 5 was wrong.** At 5 epochs the loss kept dropping but exact-match on the held-out set started regressing. Classic overfitting, but worth naming explicitly because it is tempting to "just train more."
3. **Negative examples helped more than I expected.** I had included wrong-answer continuations mostly as a defensive measure. They ended up being responsible for a noticeable chunk of the hallucination reduction.
4. **Packing was free performance.** Enabling `packing=True` in `SFTTrainer` concatenates short examples up to `max_seq_length`. My 1,800-pair dataset went from being ~5,500 tokens of useful signal per epoch (with 60% padding) to ~9,000. Same number of optimizer steps, more learning per step.
5. **The base model already knew the answers.** The fine-tune did not teach new knowledge so much as teach a specific output contract. This is the most important takeaway. Fine-tuning a small model for a narrow task is mostly about behavior, not knowledge. If you need to inject new factual knowledge, you need retrieval, not LoRA.

## Serving the result

Once training finished I merged the adapter into the base weights for serving, which is one line:

```python
merged_model = peft_model.merge_and_unload()
merged_model.save_pretrained("./final-merged")
```

A 30MB LoRA adapter on top of a 2GB base becomes a 2GB merged model that you can deploy anywhere — `vllm`, `ollama`, `llama.cpp`, a Lambda endpoint, a Raspberry Pi. I ran it locally with `llama.cpp` on an M2 MacBook and got roughly 80 tokens/second, which is plenty for an internal tool.

If you would rather keep the adapter separate, that works too. The [`peft` docs](https://huggingface.co/docs/peft) cover adapter hot-swapping and multi-adapter serving in detail.

## Key Takeaways

- **Small fine-tunes are cheap.** A 90-minute, ~$3 run on a single A100 is the new baseline. Treat fine-tuning as a normal engineering tool, not a moonshot.
- **LoRA, not full fine-tune, unless you have a reason.** Smaller artifacts, faster iteration, near-identical quality for narrow tasks.
- **The dataset is the product.** 1,800 well-shaped examples beat 50,000 scraped ones. Cap answer length, include negatives, match the test-time format exactly.
- **Eval before you train, not after.** A held-out set is the only thing standing between you and a model that has memorized your training data without learning your task.
- **Fine-tune for behavior, not knowledge.** If the model needs facts it does not have, retrieval beats training. If the model needs to answer in a specific shape and stay in its lane, fine-tuning is exactly the right tool.

## Further Reading

- [LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685) — the original paper, still the best place to start.
- [QLoRA: Efficient Finetuning of Quantized LLMs](https://arxiv.org/abs/2305.14314) — the technique I used to keep the base model in 4-bit.
- [Hugging Face PEFT documentation](https://huggingface.co/docs/peft) — covers LoRA, adapters, and serving patterns.
- [Hugging Face TRL SFTTrainer reference](https://huggingface.co/docs/trl/main/en/sft_trainer) — the trainer I used, with packing and chat-template handling.
- [Datasets for Fine-Tuning a Small LLM — a practical checklist](https://huggingface.co/blog/datasets-for-fine-tuning) — a good companion read on the data side.