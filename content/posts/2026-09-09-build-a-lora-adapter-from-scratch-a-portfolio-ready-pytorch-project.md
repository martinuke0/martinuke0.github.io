---
title: "Build a LoRA Adapter from Scratch: A Portfolio-Ready PyTorch Project"
date: "2026-09-09T12:00:45.550"
draft: false
tags: ["LoRA", "PyTorch", "BERT", "Fine-Tuning", "Low-Rank Adaptation", "Machine Learning Engineering"]
description: "Build a LoRA adapter from scratch in PyTorch with a full BERT fine-tuning loop. A hands-on guide that demonstrates real systems skills for ML engineering roles."
summary: "A hands-on build guide for implementing a LoRA adapter from scratch in PyTorch, including rank-decomposed weight matrices and a complete fine-tuning loop for BERT — designed to signal real ML engineering skill on a portfolio."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-09-build-a-lora-adapter-from-scratch-a-portfolio-ready-pytorch-project.svg"
  alt: "Low-rank adaptation diagram showing decomposed weight matrices added to a transformer layer"
  caption: ""
  relative: false
---

> **TL;DR** — LoRA (Low-Rank Adaptation) freezes the original model weights and injects small, trainable rank-decomposed matrices into each transformer layer, cutting trainable parameters by 90–99% while preserving downstream performance. This guide walks through building a complete LoRA adapter from scratch in PyTorch, wiring it into BERT, and running a full fine-tuning loop — a project that signals deep systems and ML engineering competence to any hiring manager.

---

## Why This Project Stands Out on a CV

Hiring managers in ML engineering and research filter resumes for candidates who can ship, not just theorize. A LoRA implementation from scratch demonstrates a rare cluster of skills in a single artifact:

- **Deep understanding of transformer internals.** You've manually traced how weight matrices live inside attention layers and linear projections, and you've modified them without breaking gradient flow.
- **Systems-level thinking about parameter efficiency.** You've internalized the trade-off between full fine-tuning and adapter-based methods — a pattern that extends far beyond NLP into vision, speech, and recommendation systems.
- **Production-flavored engineering.** Writing a clean, modular PyTorch module with a proper training loop, checkpointing, and evaluation metrics mirrors the workflow of real ML platforms like [Ray Train](https://docs.ray.io/en/latest/train/) or [Hugging Face Transformers](https://huggingface.co/docs/transformers/main/en/main_classes/trainer).
- **Differentiation from the crowd.** Most candidates on LinkedIn have fine-tuned a model with the Hugging Face `peft` library. Building LoRA from scratch proves you understand *why* it works, not just *how* to call it.

This project signals readiness for roles like ML Engineer, Research Engineer, or LLM Infrastructure Engineer — positions where the hiring bar is knowing whether to use LoRA, QLoRA, or prefix tuning for a given deployment constraint.

---

## Architecture Overview

The project decomposes into four tightly coupled components. Here's how they fit together:

```
┌──────────────────────────────────────────────────────┐
│                  Fine-Tuning Loop                     │
│  (DataLoader → Forward → Loss → Backward → Optimizer)│
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│              LoRA-BERT Model                          │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │         Pretrained BERT (frozen weights)      │    │
│  │  ┌─────────┐ ┌─────────┐ ┌───────────────┐  │    │
│  │  │ Embedding│ │ Encoder ×N│ │ Classifier   │  │    │
│  │  │ Layer    │ │ Layers   │ │ Head         │  │    │
│  │  └────┬────┘ └────┬────┘ └──────┬────────┘  │    │
│  └───────┼───────────┼─────────────┼───────────┘    │
│          │           │             │                │
│          ▼           ▼             ▼                │
│  ┌──────────────────────────────────────────────┐    │
│  │         LoRA Adapters (trainable)             │    │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────┐  │    │
│  │  │ W = W₀ + │  │ W = W₀ + │  │ W = W₀ +   │  │    │
│  │  │ BA       │  │ BA       │  │ BA         │  │    │
│  │  └──────────┘  └──────────┘  └────────────┘  │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

**Component breakdown:**

- **Frozen Base Model.** A pretrained BERT model (e.g., `bert-base-uncased`) whose parameters are frozen via `requires_grad_(False)`. No gradients flow into the base weights during training.
- **LoRA Adapter Modules.** For every weight matrix `W` in the target layers, LoRA replaces the update with `W = W₀ + BA`, where `B ∈ ℝ^(d × r)` and `A ∈ ℝ^(r × k)`, and `r ≪ d`. Only `B` and `A` are trained.
- **Target Layer Injection.** LoRA adapters are applied to specific linear layers — typically the query, key, value, and output projections inside each BERT attention layer, plus the feed-forward network layers.
- **Full Fine-Tuning Loop.** A standard PyTorch training loop that manages the data pipeline, loss computation (cross-entropy for classification), backpropagation through only the adapter parameters, and periodic checkpointing.

The key architectural insight is that the rank `r` controls a strict budget of trainable parameters. For a BERT layer with `d = 768`, using `r = 8` means each adapter adds only `768 × 8 × 2 = 12,288` parameters versus the original `768 × 768 = 590,592`. Across all transformer layers, this is a reduction of roughly **95–99%** in trainable parameters.

---

## Building It Step by Step

### Step 1: Project Setup and Dependencies

Create a clean virtual environment and install the required packages:

```bash
python -m venv lora-env
source lora-env/bin/activate
pip install torch torchvision transformers datasets accelerate tqdm matplotlib
```

### Step 2: The LoRA Module

This is the core of the project. The `LoRALinear` module wraps any `nn.Linear` layer, freezes the original weight, and injects the low-rank decomposition.

```python
import torch
import torch.nn as nn
import torch.nn.functional as F

class LoRALinear(nn.Module):
    """
    LoRA adapter for a single nn.Linear layer.
    Replaces W₀x with W₀x + BAx, where B and A are trainable.
    The original weight W₀ is frozen.
    """
    def __init__(self, in_features: int, out_features: int, r: int = 8,
                 alpha: float = 16.0, dropout: float = 0.1):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.r = r
        self.alpha = alpha
        # Scaling factor: alpha / r stabilizes early training
        self.scaling = alpha / r

        # Trainable low-rank matrices
        self.B = nn.Parameter(torch.zeros(in_features, r))
        self.A = nn.Parameter(torch.zeros(r, out_features))

        # Optional dropout for regularization
        self.dropout = nn.Dropout(dropout)

        # Initialize A with random orthogonal-like values, B with zeros
        # This ensures the adapter starts as an identity update
        nn.init.kaiming_uniform_(self.A, a=math.sqrt(5))
        nn.init.zeros_(self.B)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Original frozen weight contribution is handled by the caller
        # We only compute the low-rank update: BAx
        # x shape: (*batch, in_features)
        x = self.dropout(x)
        # Efficient computation: x → Aᵀ → BAᵀ → BAᵀx
        # (r × in) @ (in × batch_batch) then (out × r) @ result
        result = self.A.T @ (self.B.T @ x)  # shape: (out_features, ...)
        return result * self.scaling
```

### Step 3: Injecting LoRA into BERT Layers

We target the attention projection layers (`query`, `key`, `value`, `dense`) and the feed-forward layers (`intermediate`, `output`) inside each BERT encoder layer.

```python
import math
from transformers import BertModel, BertConfig

class LoRABertForSequenceClassification(nn.Module):
    """
    BERT for sequence classification with LoRA adapters injected
    into attention and FFN layers. Base BERT weights are frozen.
    """
    def __init__(self, model_name: str = "bert-base-uncased",
                 num_labels: int = 2, r: int = 8, alpha: float = 16.0):
        super().__init__()
        self.bert = BertModel.from_pretrained(model_name)
        self.classifier = nn.Linear(self.bert.config.hidden_size, num_labels)

        # Freeze all BERT parameters
        for param in self.bert.parameters():
            param.requires_grad = False

        # Inject LoRA into target layers
        self._inject_lora(r, alpha)

    def _inject_lora(self, r: int, alpha: float):
        """
        Walk through BERT's encoder layers and replace
        specific Linear modules with LoRALinear wrappers.
        """
        target_modules = [
            "attention.self.query",
            "attention.self.key",
            "attention.self.value",
            "attention.output.dense",
            "intermediate.dense",
            "output.dense",
        ]

        for layer_idx, layer in enumerate(self.bert.encoder.layer):
            for attr_path in target_modules:
                parts = attr_path.split(".")
                module = layer
                for part in parts[:-1]:
                    module = getattr(module, part)
                last_attr = parts[-1]
                original = getattr(module, last_attr)

                if isinstance(original, nn.Linear):
                    # Create LoRA wrapper
                    lora = LoRALinear(
                        in_features=original.in_features,
                        out_features=original.out_features,
                        r=r, alpha=alpha
                    )
                    # Replace the module
                    setattr(module, last_attr, lora)

    def forward(self, input_ids: torch.Tensor,
                attention_mask: torch.Tensor) -> torch.Tensor:
        # BERT forward — base weights frozen, only LoRA adapters train
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        # Use  token representation for classification
        cls_output = outputs.last_hidden_state[:, 0, :]
        logits = self.classifier(cls_output)
        return logits
```

**Critical detail:** The `forward` pass of `LoRALinear` must be called *in addition to* the original `nn.Linear` forward pass. In the code above, because we replace `nn.Linear` entirely with `LoRALinear`, the original weight contribution is lost. The correct approach is to subclass `nn.Linear` and override `forward`:

```python
class LoRALinear(nn.Linear):
    """
    Correct approach: subclass nn.Linear so the original
    weight W₀ is still used, and we add the BA update on top.
    """
    def __init__(self, in_features: int, out_features: int, r: int = 8,
                 alpha: float = 16.0, dropout: float = 0.1, **kwargs):
        super().__init__(in_features, out_features, **kwargs)
        self.r = r
        self.alpha = alpha
        self.scaling = alpha / r
        self.dropout = nn.Dropout(dropout)

        # Trainable low-rank matrices
        self.lora_A = nn.Parameter(torch.zeros(r, in_features))
        self.lora_B = nn.Parameter(torch.zeros(out_features, r))

        # Initialize A randomly, B at zeros (identity start)
        nn.init.kaiming_uniform_(self.lora_A, a=math.sqrt(5))
        nn.init.zeros_(self.lora_B)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Original linear transformation: W₀x + b
        # Then add the LoRA update: BAx * scaling
        x = self.dropout(x)
        lora_update = (self.lora_B @ self.lora_A) @ x.T
        lora_update = lora_update * self.scaling
        # Compute original linear output
        original = F.linear(x, self.weight, self.bias)
        # Sum: original output + LoRA update
        return original + lora_update.T
```

This subclassing approach is the architecturally correct pattern — the original weight matrix `W₀` remains in the computation graph and is frozen via `requires_grad_(False)`, while only `lora_A` and `lora_B` accumulate gradients.

### Step 4: The Full Fine-Tuning Loop

With the model wired up, here is the complete training pipeline:

```python
from torch.utils.data import DataLoader
from transformers import BertTokenizer, get_linear_schedule_with_warmup
from datasets import load_dataset
from tqdm import tqdm
import torch.optim as optim

def train_lora(model: LoRABertForSequenceClassification,
               train_dataset, val_dataset,
               epochs: int = 3, batch_size: int = 16,
               lr: float = 2e-4, weight_decay: float = 0.01):

    tokenizer = BertTokenizer.from_pretrained("bert-base-uncased")
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size)

    # Optimizer: ONLY train LoRA parameters + classifier
    optimizer = optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=lr, weight_decay=weight_decay
    )

    total_steps = len(train_loader) * epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=total_steps // 10,
        num_training_steps=total_steps
    )

    criterion = nn.CrossEntropyLoss()

    for epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        correct = 0
        total = 0

        progress_bar = tqdm(train_loader, desc=f"Epoch {epoch+1}/{epochs}")
        for batch in progress_bar:
            input_ids = batch["input_ids"]
            attention_mask = batch["attention_mask"]
            labels = batch["label"]

            optimizer.zero_grad()

            logits = model(input_ids, attention_mask)
            loss = criterion(logits, labels)
            loss.backward()

            # Gradient clipping for stability
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad],
                max_norm=1.0
            )

            optimizer.step()
            scheduler.step()

            epoch_loss += loss.item()
            preds = logits.argmax(dim=-1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

            progress_bar.set_postfix({
                "loss": f"{loss.item():.4f}",
                "acc": f"{correct/total:.3f}"
            })

        # Validation step
        val_acc = evaluate(model, val_loader, criterion)
        print(f"Epoch {epoch+1} — Val Accuracy: {val_acc:.4f}")

        # Checkpoint only trainable parameters to keep files small
        torch.save({
            "epoch": epoch,
            "model_state": {
                k: v for k, v in model.state_dict().items()
                if "lora_" in k or "classifier" in k
            },
            "optimizer_state": optimizer.state_dict(),
        }, f"checkpoint_epoch_{epoch+1}.pt")

def evaluate(model, val_loader, criterion):
    model.eval()
    correct = 0
    total = 0
    total_loss = 0.0

    with torch.no_grad():
        for batch in val_loader:
            logits = model(batch["input_ids"], batch["attention_mask"])
            loss = criterion(logits, batch["label"])
            total_loss += loss.item()
            preds = logits.argmax(dim=-1)
            correct += (preds == batch["label"]).sum().item()
            total += batch["label"].size(0)

    return correct / total
```

### Step 5: Data Preparation and Main Entry Point

```python
from datasets import load_dataset

def main():
    # Load a benchmark dataset — SST-2 for sentiment classification
    dataset = load_dataset("sst2")

    tokenizer = BertTokenizer.from_pretrained("bert-base-uncased")

    def tokenize_fn(examples):
        return tokenizer(
            examples["sentence"],
            padding="max_length",
            truncation=True,
            max_length=128,
            return_tensors="pt"
        )

    tokenized_train = dataset["train"].map(tokenize_fn, batched=True)
    tokenized_val = dataset["validation"].map(tokenize_fn, batched=True)

    tokenized_train.set_format("torch", columns=["input_ids", "attention_mask", "label"])
    tokenized_val.set_format("torch", columns=["input_ids", "attention_mask", "label"])

    model = LoRABertForSequenceClassification(
        model_name="bert-base-uncased",
        num_labels=2,
        r=8,          # Rank — the key hyperparameter
        alpha=16.0    # Scaling
    )

    # Count trainable parameters to verify the reduction
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(
        p.numel() for p in model.parameters() if p.requires_grad
    )
    print(f"Total parameters: {total_params:,}")
    print(f"Trainable parameters: {trainable_params:,}")
    print(f"Trainable ratio: {trainable_params/total_params:.4%}")

    train_lora(model, tokenized_train, tokenized_val, epochs=3)

if __name__ == "__main__":
    main()
```

---

## Running and Testing It

### Local Execution

Clone the project, activate the environment, and run:

```bash
python main.py
```

You should see output confirming the parameter reduction — typically around **0.4–0.8%** of the total BERT parameters are trainable. For `bert-base-uncased` (~110M parameters), that means roughly **450K–900K** trainable parameters instead of 110M.

### Verification Checklist

To prove the implementation is correct, run these assertions:

```python
# Verify base weights are frozen
for name, param in model.named_parameters():
    if "lora_" not in name and "classifier" not in name:
        assert not param.requires_grad, f"{name} should be frozen!"

# Verify LoRA parameters exist and are trainable
lora_params = [p for p in model.parameters() if "lora_" in p.name or p.requires_grad]
assert len(lora_params) > 0, "No LoRA parameters found!"

# Verify the adapter starts near identity (zero update)
with torch.no_grad():
    lora_b = model.bert.encoder.layer[0].attention.self.query.lora_B
    assert torch.allclose(lora_b, torch.zeros_like(lora_b)), \
        "LoRA B should initialize to zeros for identity start"
```

### Expected Training Curve

With `r=8`, `lr=2e-4`, and 3 epochs on SST-2, you should see validation accuracy climb to **~90–92%**, which is competitive with full fine-tuning on this dataset. If accuracy stalls below 85%, check that:

1. The `requires_grad_(False)` flag is applied to base BERT parameters.
2. The optimizer only receives parameters where `requires_grad=True`.
3. The LoRA scaling factor (`alpha/r`) is reasonable — try `alpha=16, r=8` or `alpha=32, r=16`.

---

## Extending It: Your Roadmap to Senior-Level

The base implementation is a strong portfolio piece, but the following upgrades transform it into something that reads like production infrastructure:

1. **Add checkpoint resume and fault-tolerant training.** Implement a `Trainer` class that automatically resumes from the latest checkpoint on interruption, handling `KeyboardInterrupt` and `SIGTERM` gracefully. This matters because distributed training jobs on cloud GPUs routinely fail mid-epoch, and the ability to resume without losing progress is a baseline expectation in production ML.

2. **Integrate Weights & Biases (W&B) or MLflow for experiment tracking.** Log every hyperparameter combination, loss curve, and validation metric to a centralized dashboard. This matters because without systematic logging, hyperparameter tuning becomes guesswork and reproducibility collapses when you need to reproduce a result three weeks later.

3. **Implement gradient accumulation for larger effective batch sizes.** Modify the training loop to accumulate gradients over `n` micro-batches before calling `optimizer.step()`. This matters because consumer GPUs (e.g., a single RTX 4090 with 24GB VRAM) cannot fit large batch sizes needed for stable convergence, and gradient accumulation is the standard technique to simulate large-batch training on constrained hardware.

4. **Add LoRA rank ablation studies with automated reporting.** Write a script that sweeps `r ∈ {4, 8, 16, 32, 64}` and `alpha ∈ {8, 16, 32, 64}` across all runs, generating comparison tables and plots. This matters because choosing the right rank is the central engineering decision in LoRA deployment — too low and performance collapses, too high and the memory benefit evaporates.

5. **Containerize with Docker and add a CI/CD pipeline.** Build a `Dockerfile` that pins all dependencies, and set up GitHub Actions to run the training pipeline on every push, with automatic pytest validation. This matters because reproducibility and automated testing are non-negotiable in production ML systems, and containerization ensures the environment is identical across your laptop, a colleague's machine, and the cloud GPU cluster.

6. **Implement mixed-precision training with `torch.cuda.amp`.** Wrap the forward and backward passes in `torch.autocast` and `GradScaler` to use FP16 computation where safe. This matters because mixed precision cuts GPU memory usage by roughly 40% and speeds up training by 1.5–3× on modern Ampere+ architectures, making it a free performance win that every production training job uses.

---

## Key Takeaways

- LoRA reduces trainable parameters by **95–99%** by freezing the base model and adding rank-decomposed `B` and `A` matrices, making it practical to fine-tune large models on consumer hardware.
- The correct implementation pattern is to **subclass `nn.Linear`** so the original weight matrix stays in the computation graph while the low-rank update is added on top.
- A clean, modular architecture — separate LoRA module, model injection, and training loop — is what transforms a toy script into a portfolio project that signals production readiness.
- Parameter efficiency is not just an NLP trick; the same adapter pattern applies to **vision transformers, recommendation systems, and diffusion models**, making this skill broadly transferable.
- The real differentiator on a CV is not just building it, but **extending it** — adding experiment tracking, fault tolerance, and benchmarking demonstrates the systems thinking that separates ML engineers from ML researchers.
- Always verify that `requires_grad` flags and optimizer parameter lists are consistent — a single misconfigured parameter is the most common reason LoRA implementations silently train the entire model.

---

## Further Reading

- [LoRA: Low-Rank Adaptation of Large Language Models (Hu et al., 2021)](https://arxiv.org/abs/2106.09685) — The original paper introducing the LoRA method. Read this first to understand the theoretical motivation and empirical results.
- [Hugging Face PEFT Library Documentation](https://huggingface.co/docs/peft/main/en/index) — The official library for parameter-efficient fine-tuning. Study their `get_peft_model` implementation to see how they handle layer targeting and merging at inference time.
- [PyTorch `nn.Linear` Source Code](https://pytorch.org/docs/stable/generated/torch.nn.Linear.html) — Understanding the exact forward computation of `F.linear(x, weight, bias)` is essential for correctly subclassing it with LoRA adapters.
- [Training Transformers with LoRA: Best Practices](https://www.sebastianraschka.com/blog/2023/llm-fine-tuning-lora.html) — Sebastian Raschka's practical guide covering rank selection, learning rate schedules, and when to use LoRA versus full fine-tuning.
- [BERT: Pre-training of Deep Bidirectional Transformers (Devlin et al., 2018)](https://arxiv.org/abs/1810.04805) — The original BERT paper. Understanding the architecture layer structure is necessary for knowing exactly which modules to target with LoRA adapters.
- [Mixed Precision Training (NVIDIA)](https://docs.nvidia.com/deeplearning/performance/mixed-precision-training/index.html) — The canonical reference on why and how mixed precision training works, including the numerical considerations that make FP16 safe for certain operations.
- [PyTorch `torch.cuda.amp` Documentation](https://pytorch.org/docs/stable/amp.html) — Official documentation for implementing automatic mixed precision, which is upgrade #6 in the senior-level roadmap.

---

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
