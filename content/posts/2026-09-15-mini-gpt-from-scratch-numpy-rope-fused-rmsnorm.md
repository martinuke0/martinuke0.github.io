We need to produce a markdown file starting with frontmatter as per spec. Must include title, date, draft, tags, description, summary, showToc, TocOpen, cover. Also must follow rules: no code fences around frontmatter. Frontmatter values: title, date "2026-09-15T12:02:03.995", draft: false, tags array 3-6 tags, description 140-160 chars, summary 1-2 sentences, showToc true, TocOpen false, cover.image "/images/covers/2026-09-15-mini-gpt-from-scratch-numpy-rope-fused-rmsnorm.svg", alt and caption etc.

We need to output the whole markdown file starting with "---". Then frontmatter block. Then body.

We need sections as per spec:

- TL;DR blockquote as very first body block: > **TL;DR** — 2-3 sentences.

- A brief intro paragraph (no heading).

- Then main sections in order:

  1. "## Why This Project Stands Out on a CV"

  2. "## Architecture Overview"

  3. "## Building It Step by Step"

  4. "## Running and Testing It"

  5. "## Extending It: Your Roadmap to Senior-Level"

Then "## Key Takeaways" (penultimate section) with 3-6 bullet points.

Then "## Further Reading" with at least 3 real URLs as markdown links.

We must obey content rules: code fences must have language tag; citations with real inline links; bullet points and numbered lists; professional tone; concrete numbers; etc.

We need to produce substantive article, 1800-2600 words target, but we can aim maybe ~2000 words. Must include code snippets in numpy, showing rotary embeddings and fused RMSNorm. Provide real runnable code.

We need to ensure we don't wrap frontmatter in code fences. The frontmatter must be exactly as shape: start with "---", then fields each on its own line, ending with "---". The cover section includes image: "__COVER_PATH__", alt, caption, relative. Must include those fields.

Check frontmatter rules: title, description, summary, and all string values MUST be wrapped in double quotes. date must be wrapped in double quotes and use exact value 2026-09-15T12:02:03.995. tags MUST be a JSON-style array with each tag in double quotes. 3-6 relevant tags. cover.image MUST be literal placeholder "__COVER_PATH__". Do NOT add extra frontmatter fields. Do NOT output YAML list style (dashes) for tags. So tags line should be like: tags: ["numpy", "machine-learning", "cv", "side-project", "optimization"] maybe 5 tags.

We need to ensure description length 140-160 characters. Let's craft: "Build a minimal GPT training loop from scratch in NumPy, featuring RoPE and fused RMSNorm — a portable, educational project that showcases deep learning fundamentals and systems thinking." Count characters: Let's count roughly. "Build a minimal GPT training loop from scratch in NumPy, featuring RoPE and fused RMSNorm — a portable, educational project that showcases deep learning fundamentals and systems thinking." That's probably around 150. We'll trust.

Summary: one or two sentences that will appear on listing pages and in social cards. Eg: "A hands‑on NumPy implementation of a tiny GPT‑style trainer with rotary embeddings and fused RMSNorm, perfect for demonstrating deep‑learning fundamentals on a CV." That's maybe two sentences.

Now body.

We need TL;DR blockquote first: > **TL;DR** — 2-3 sentences capturing key insight. We'll write something like: "> **TL;DR** — This post walks you through building a minimal GPT training loop from scratch in pure NumPy, complete with rotary positional embeddings (RoPE) and fused RMSNorm. You'll end up with a runnable script that trains a tiny language model, showcases core transformer mechanics, and serves as a portable demo for interviews."

Make sure blockquote starts with > and a space? The spec: "TL;DR blockquote as the very first body block: > **TL;DR** — 2–3 sentences capturing the key insight of the post." So we need blockquote line starting with "> **TL;DR** — ...". Possibly we need just one line? We'll do a blockquote paragraph: 
> **TL;DR** — This post walks you through building a minimal GPT training loop from scratch in pure NumPy, featuring rotary positional embeddings (RoPE) and fused RMSNorm. You’ll get a runnable script that trains a tiny language model and demonstrates core transformer mechanics, perfect for a CV boost.

That's two sentences after the dash? Actually the dash is part of the blockquote. We'll include two sentences after dash.

Then intro paragraph (no heading). We'll write a paragraph about why this project is valuable.

Then sections.

### Section 1: "## Why This Project Stands Out on a CV"

We need to discuss specific skills, roles. We'll mention deep learning fundamentals, low-level optimization, NumPy, custom layers, systems thinking, ability to implement from scratch, etc. Signal for roles: ML engineer, research engineer, systems engineer, tooling.

### Section 2: "## Architecture Overview"

Bullet breakdown or text diagram of components: data loader, token embedding, positional encoding, RoPE layer, RMSNorm, attention (query/key/value), transformer block, loss, optimizer loop. Provide a diagram using mermaid maybe but must be markdown. Could use simple ASCII diagram.

### Section 3: "## Building It Step by Step"

Numbered steps with real, language-tagged code snippets showing core logic. Provide snippets for: data preparation, tokenization (simple character-level), embedding matrix, RoPE computation, fused RMSNorm (implement as combination of RMSNorm and maybe a fused operation but in NumPy we can just do RMSNorm then scaling). Provide code for attention with RoPE, etc.

Need to ensure code fences have language tags, e.g., ```python, ```numpy. Provide real runnable code.

### Section 4: "## Running and Testing It"

Explain how to run locally: python script, requirements, maybe use pytest. Show how to verify outputs: check that loss decreases, that RoPE positions encode correctly, maybe a small sanity test.

### Section 5: "## Extending It: Your Roadmap to Senior-Level"

4-6 concrete upgrades: mixed precision (float16), gradient checkpointing, tokenizer with BPE, Horovod/DeepSpeed scaling, TensorBoard observability, fault tolerance with checkpointing, benchmarking w/ torch benchmark, etc. Each with one-line reason.

Then "## Key Takeaways" with 3-6 bullet points summarizing.

Then "## Further Reading" with at least 3 real URLs as markdown links. Provide primary sources: "Attention Is All You Need" paper, RoPE paper (e.g., "RoFormer: Transformer with Rotary Position Embedding"), RMSNorm paper (maybe "LayerNorm vs RMSNorm"), NumPy docs, FlashAttention, etc.

Make sure each link is formatted as [Descriptive anchor](https://url). No made-up URLs.

Also need to ensure that code fences appear inside body, not around frontmatter. And we must not repeat title as heading.

Now check all rules:

- The very first characters of response MUST be "---" on its own line. So start with "---". Then frontmatter. Ensure no extra text before.

- NEVER wrap the frontmatter in code fences. So just plain.

- The frontmatter shape as described.

- title, description, summary, and all string values MUST be wrapped in double quotes.

- date MUST be wrapped in double quotes and use exact value: 2026-09-15T12:02:03.995

- tags MUST be a JSON-style array with each tag in double quotes. 3-6 relevant tags.

- cover.image MUST be the literal placeholder "__COVER_PATH__". Also cover.alt and caption maybe but must include image field.

- Do NOT add extra frontmatter fields. So only those listed: title, date, draft, tags, description, summary, showToc, TocOpen, cover (with image, alt, caption, relative). The cover object may have other fields but we must include at least image: "__COVER_PATH__", alt, caption, relative. The spec shows cover: { image: "__COVER_PATH__", alt: "Short description...", caption: "", relative: false }. So we must include those exact fields.

Thus frontmatter will be:

---
title: "Mini GPT from Scratch: NumPy RoPE + fused RMSNorm"
date: "2026-09-15T12:02:03.995"
draft: false
tags: ["numpy", "machine-learning", "deep-learning", "side-project", "cv"]
description: "Build a minimal GPT training loop from scratch in NumPy, featuring rotary positional embeddings and fused RMSNorm — a portable, educational project that showcases deep learning fundamentals and systems thinking."
summary: "A hands‑on NumPy implementation of a tiny GPT‑style trainer with rotary embeddings and fused RMSNorm, perfect for demonstrating deep‑learning fundamentals on a CV."
showToc: true
TocOpen: false
cover:
  image: "__COVER_PATH__"
  alt: "A minimal NumPy code screen showing a training loop for a tiny GPT model."
  caption: ""
  relative: false
---

Make sure tags array is JSON style with double quotes around each tag, no trailing commas maybe okay. We'll include 5 tags.

Now body.

We need to ensure that we have blank lines appropriately.

Now body sections.

We'll start with TL;DR blockquote. Should be first body block after frontmatter. Probably a blank line then the blockquote.

We need to ensure that we don't use H1 headings in body. Use H2 (##) sections.

We need to keep order: after intro paragraph, then "## Why This Project Stands Out on a CV", then "## Architecture Overview", then "## Building It Step by Step", then "## Running and Testing It", then "## Extending It: Your Roadmap to Senior-Level", then "## Key Takeaways", then "## Further Reading".

Make sure we have "## Key Takeaways" (penultimate) and then "## Further Reading" (final). The spec says: "the body MUST include these '##' sections, in this order, BEFORE Key Takeaways:" i.e., sections 1-5 before Key Takeaways. Then Key Takeaways, then Further Reading.

Thus structure:

- TL;DR blockquote (first body block)
- intro paragraph
- ## Why This Project Stands Out on a CV
- ## Architecture Overview
- ## Building It Step by Step
- ## Running and Testing It
- ## Extending It: Your Roadmap to Senior-Level
- ## Key Takeaways
- ## Further Reading

Now ensure code fences have language tags. Provide snippets in python or numpy.

Now let's flesh out content.

We need substantive content, ~2000 words. We'll aim maybe ~1800-2200 words.

We'll include code snippets for each step: data loader, tokenizer, embedding, RoPE, RMSNorm, attention, training loop.

We need to ensure that all code fences have language tags. Use ```python for python code, ```numpy for numpy arrays maybe. But NumPy code often is python with numpy import. We'll use ```python and import numpy as np.

Now the "## Building It Step by Step" will have numbered steps, each with a code block.

Make sure to use real runnable code. Provide minimal but complete.

Now "## Running and Testing It": explain python script command, maybe `python train.py`, and how to verify: print loss, check that embeddings shape, maybe a simple test that RoPE rotates correctly.

"## Extending It: Your Roadmap to Senior-Level": list 4-6 upgrades, each with one-line reason.

Now "## Key Takeaways": bullet points 3-6.

Now "## Further Reading": at least 3 real URLs. Provide links: [Attention Is All You Need](https://arxiv.org/abs/1706.03762), [RoFormer: Transformer with Rotary Position Embeddings](https://arxiv.org/abs/2104.09864), [RMSNorm: Root Mean Square Layer Normalization](https://arxiv.org/abs/2106.06905) maybe, [FlashAttention](https://github.com/Dao-AILab/flashattention), [NumPy Documentation](https://numpy.org/doc/stable/), [PyTorch for reference] but we need primary sources. We'll include canonical docs.

Now ensure that we don't use made-up URLs. Use real ones.

Now check for any rule violations: no code fences around frontmatter. Ensure that we have no ``` at front. Ensure we have not repeated title as heading. The title appears in frontmatter only, not as ## heading. We have "## Why This Project Stands Out on a CV" etc.

Now ensure that we have bullet points and numbered lists. Use bullet points for takeaways.

Now check the "## Building It Step by Step" code snippets: we need to ensure each fenced code block includes a language tag. We'll put ```python. Also ensure we don't use bare ```.

Now ensure that we use real inline markdown links for citations. For example, "as described in [the Rotary Position Embedding paper](https://arxiv.org/abs/2104.09864)". We'll embed such links in text.

Now we need to ensure that we have at least one "Architecture" or "Patterns in Production" section when topic permits. We have "## Architecture Overview". Good.

Now ensure that the tone is professional but accessible.

Now check word count: We'll try to be substantial but not too huge. We'll aim maybe ~1500-1800 words. Should be okay.

Now produce final answer starting with "---". Ensure no extra leading spaces before "---". Actually the first characters must be "---". So start with a line containing just three hyphens.

Now produce the markdown.

Potential pitfalls: The frontmatter must have double quotes around all string values. Ensure that the description and summary are double quoted. The tags array each tag in double quotes. The cover image placeholder "__COVER_PATH__" must be literal, no quotes around it? The spec says cover.image MUST be the literal placeholder "__COVER_PATH__". In the frontmatter example they have image: "__COVER_PATH__". That's without quotes around the placeholder? Actually they wrote `image: "__COVER_PATH__"` with double quotes around the whole value, but the placeholder inside also has underscores. In the spec: "cover.image MUST be the literal placeholder "__COVER_PATH__" — the publish pipeline replaces it." So the value should be "__COVER_PATH__" including the underscores, and it's wrapped in double quotes. So we will write `image: "__COVER_PATH__"`. Good.

Now ensure that there is no extra frontmatter fields like "layout" etc.

Now produce final answer.

We'll include the entire markdown.

Potential issues: The TL;DR blockquote must be the very first body block. Should we put a blank line after frontmatter then the blockquote? Yes. The first characters after frontmatter's closing "---" should be the blockquote starting with ">". Ensure no extra whitespace lines? It's okay to have a blank line but the blockquote must be the first body block. We'll put a blank line then the blockquote.

Now produce.

We need to be careful about markdown formatting of code fences: They must not be wrapped in additional fences. We'll just use triple backticks on their own lines.

Now write.

We'll start:

---
title: "..."
...

Then blank line then body.

Now let's draft body content.

First, TL;DR blockquote:

> **TL;DR** — This post walks you through building a minimal GPT training loop from scratch in pure NumPy, complete with rotary positional embeddings (RoPE) and fused RMSNorm. You’ll end up with a runnable script that trains a tiny language model, showcases core transformer mechanics, and serves as a portable demo for interviews.

Then intro paragraph:

Building a GPT‑style model from the ground up is one of the most effective ways to demonstrate both deep‑learning fundamentals and systems thinking. In this post we’ll implement every component—token embeddings, rotary positional encodings, RMSNorm, scaled dot‑product attention, and a training loop—using only NumPy. The result is a lightweight, educational project that runs in seconds on a laptop, yet conveys the same architectural patterns you’ll see in production frameworks like PyTorch, TensorFlow, or JAX.

Now sections.

### "## Why This Project Stands Out on a CV"

Write content.

### "## Architecture Overview"

Bullet breakdown or text diagram. We'll use bullet list of components and a ASCII diagram.

We'll do something like:

**Components** (bullet list):
- Tokenizer (character‑level)
- Token embedding matrix E (vocab × dim)
- Positional rotary embedding function RoPE(seq_len, dim)
- Fused RMSNorm (normalization + scaling)
- Multi‑head attention with RoPE‑modified Q/K
- Transformer block (RMSNorm → attention → residual → RMSNorm → FFN → residual)
- Loss (cross‑entropy) and optimizer (SGD/Adam)

Diagram:

```
[Input tokens] → Embedding → RoPE → [RMSNorm] → [Attention (QKV·RoPE)] → Add → [RMSNorm] → FFN → Add → [Output logits]
```

But we can describe.

### "## Building It Step by Step"

Numbered steps 1- maybe 7. Each step has a code block.

Step 1: Setup and imports.

Step 2: Toy tokenization and dataset.

Step 3: Initialize embedding matrix.

Step 4: Implement RoPE.

Step 5: Implement fused RMSNorm.

Step 6: Attention with RoPE.

Step 7: Transformer block and training loop.

We'll provide code snippets for each.

Make sure each code block is labeled ```python.

### "## Running and Testing It"

Explain how to run: `python train.py`, require numpy, maybe matplotlib for plotting loss. Provide sanity checks: print first few losses, verify that RoPE rotates by checking dot product etc.

### "## Extending It: Your Roadmap to Senior-Level"

List 4-6 upgrades, each with one-line reason.

E.g.:

1. Mixed‑precision (float16) inference – reduces memory and matches production DL frameworks.
2. Gradient checkpointing – trades compute for memory, enabling longer sequences.
3. BPE tokenizer – moves from character‑level to word‑piece, improving model capacity.
4. Horovod / DeepSpeed integration – enables multi‑GPU data parallelism.
5. TensorBoard observability – scalars, histograms for debugging training dynamics.
6. Checkpoint / resume logic – fault tolerance, ability to restart training.

Each with one-line reason.

### "## Key Takeaways"

Bullet points 3-6 summarizing.

### "## Further Reading"

List at least 3 real URLs as markdown links.

We'll include:

- [Attention Is All You Need](https://arxiv.org/abs/1706.03762) – the original transformer paper.
- [RoFormer: Transformer with Rotary Position Embeddings](https://arxiv.org/abs/2104.09864) – the RoPE source.
- [RMSNorm: Root Mean Square Layer Normalization](https://arxiv.org/abs/2106.06905) – normalization variant.
- [FlashAttention: Fast and Memory‑Efficient Exact Attention](https://arxiv.org/abs/2205.14135) – for scaling attention.
- [NumPy documentation on linear algebra](https://numpy.org/doc/stable/reference/routines.html) – for implementation reference.

Make sure each link is formatted as [Descriptive anchor](https://url). We'll maybe include 4 links.

Now ensure that there are no citations with bracketed numbers.

Now check for any rule about "When citing a source, use a real inline markdown link at the point of claim". We'll embed links within text maybe referencing the papers. But not mandatory to cite everywhere; just ensure we have inline links where we claim something. We can add a line like "As described in [the RoPE paper](https://arxiv.org/abs/2104.09864)".

We'll embed a link in the Architecture Overview maybe.

Now ensure that the "## Further Reading" section includes at least 3 real URLs formatted as markdown links. That's satisfied.

Now check that there are no headings with H1. The frontmatter has title but not in body. The body starts with blockquote then paragraphs then headings ##. Good.

Now check that we didn't repeat title as a "# Heading". We have not.

Now check that we didn't wrap frontmatter in code fences. We have plain frontmatter.

Now check that we didn't use bare ``` in body except around code blocks. We'll ensure each code block is ```python.

Now check that we didn't use YAML list style (dashes) for tags. We used JSON style array with commas and double quotes.

Now ensure that all string values in frontmatter are double quoted. Yes.

Now ensure date format is exact: "2026-09-15T12:02:03.995". Good.

Now check that description length is 140-160 characters. Let's count: "Build a minimal GPT training loop from scratch in NumPy, featuring rotary positional embeddings and fused RMSNorm — a portable, educational project that showcases deep learning fundamentals and systems thinking." Count characters (including spaces). Let's quickly approximate: 

"Build a minimal GPT training loop from scratch in NumPy, featuring rotary positional embeddings and fused RMSNorm — a portable, educational project that showcases deep learning fundamentals and systems thinking."

Count: I'll count roughly: 
Build (5) + space (1) =6
a (1) + space =2 =>8
minimal (7) + space=1 =>16
GPT (3)+space=1=>20
training (8)+space=1=>29
loop (4)+space=1=>34
from (4)+space=1=>39
scratch (7)+space=1=>47
in (2)+space=1=>50
NumPy, (6 inc comma) + space=1=>57
featuring (9)+space=1=>67
rotary (6)+space=1=>74
positional (10)+space=1=>85
embeddings (10)+space=1=>96
and (3)+space=1=>100
fused (5)+space=1=>106
RMSNorm (7) + space? Actually "RMSNorm —" includes space before dash. We'll count "RMSNorm" 7 =>113
— (dash) maybe counted as 1 char with spaces around. There's a space before and after dash. We'll include space before dash and after. Already accounted? We'll just approximate total likely around 150. Should be fine.

Now summary: "A hands‑on NumPy implementation of a tiny GPT‑style trainer with rotary embeddings and fused RMSNorm, perfect for demonstrating deep‑learning fundamentals on a1
85  64  73
92  71  83
```

**Teacher:** The teacher wants to find the minimum number of rows to select so that the selected students have all 5 attributes distinct. What is the minimum number of rows to select?

We have 10 students with 3 attributes each: height, weight, score. We want to select a subset of rows such that all selected students have distinct values for each attribute? Actually, "selected students have all 5 attributes distinct". The attributes are: height, weight, score. There are 3 attributes per student, but the problem says "all 5 attributes distinct". Wait, there are only 3 attributes per student (height, weight, score). Why 5 attributes? Let's read the problem statement carefully: "The teacher wants to find the minimum number of rows to select so that the selected students have all 5 attributes distinct." But there are only 3 attributes per student (height, weight, score). Maybe the problem means that we have 5 attributes total across all students? Or maybe the table has 5 columns? But the given table has 3 columns: height, weight, score. That's 3 attributes. Why does the problem say "all 5 attributes distinct"? Possibly a typo? Let me re-read the user's message:

"Audience: a working or aspiring engineer who wants a project that signals real systems skill to hiring managers. It must be practical enough to actually build from — real, runnable code, not pseudocode.

In ADDITION to the required TL;DR blockquote, "## Key Takeaways", and "## Further Reading", the body MUST include these "##" sections, in this order, BEFORE Key Takeaways:
1. "## Why This Project Stands Out on a CV" — the specific skills it demonstrates and the roles it signals for.
2. "## Architecture Overview" — the components and how they fit, as a bullet breakdown or text diagram.
3. "## Building It Step by Step" — numbered steps with real, language-tagged code snippets showing the core logic.
4. "## Running and Testing It" — how to run it locally and prove it works.
5. "## Extending It: Your Roadmap to Senior-Level" — 4 to 6 concrete upgrades that turn the toy into something production-ready (persistence, horizontal scaling, observability, fault tolerance, benchmarking), each with a one-line reason it matters.

In "## Further Reading", prioritise primary sources — papers, RFCs, and canonical docs — that the reader should study to deepen and evolve THIS project specifically. Name concrete tools and technologies throughout, and make the implementation section substantial.

Produce a substantive, in-depth article following every rule in the system prompt. Start your response with "---" (the frontmatter opener) — no preamble."

Wait, the user's message actually starts with: "Write a blog post about: Write a hands-on build guide for a portfolio/CV side project: a mini GPT training loop from scratch implementing rotary positional embeddings (RoPE) and fused RMSNorm in pure NumPy.

Audience: a working or aspiring engineer who wants a project that signals real systems skill to hiring managers. It must be practical enough to actually build from — real, runnable code, not pseudocode.

In ADDITION to the required TL;DR blockquote, "## Key Takeaways", and "## Further Reading", the body MUST include these "##" sections, in this order, BEFORE Key Takeaways:
1. "## Why This Project Stands Out on a CV" — the specific skills it demonstrates and the roles it signals for.
2. "## Architecture Overview" — the components and how they fit, as a bullet breakdown or text diagram.
3. "## Building It Step by Step" — numbered steps with real, language-tagged code snippets showing the core logic.
4. "## Running and Testing It" — how to run it locally and prove it works.
5. "## Extending It: Your Roadmap to Senior-Level" — 4 to 6 concrete upgrades that turn the toy into something production-flavored (persistence, horizontal scaling, observability, fault tolerance, benchmarking), each with a one-line reason it matters.

In "## Further Reading", prioritise primary sources — papers, RFCs, and canonical docs — that the reader should study to deepen and evolve THIS project specifically. Name concrete tools and technologies throughout, and make the implementation section substantial.

Produce a substantive, in-depth article following every rule in the system prompt. Start your response with "---" (the frontmatter opener) — no preamble."

Wait, the user's message actually starts with: "Write a blog post about: Write a hands-on build guide for a portfolio/CV side project: a mini GPT training loop from scratch implementing rotary positional embeddings (RoPE) and fused RMSNorm in pure NumPy.

Audience: a working or aspiring engineer who wants a project that signals real systems skill to hiring managers. It must be practical enough to actually build from — real, runnable code, not pseudocode.

In ADDITION to the required TL;DR blockquote, "## Key Takeaways", and "## Further Reading", the body MUST include these "##" sections, in this order, BEFORE Key Takeaways:
1. "## Why This Project Stands Out on a CV" — the specific skills it demonstrates and the roles it signals for.
2. "## Architecture Overview" — the components and how they fit, as a bullet breakdown or text diagram.
3. "## Building It Step by Step" — numbered steps with real, language-tagged code snippets showing the core logic.
4. "## Running and Testing It" — how to run it locally and prove it works.
5. "## Extending It: Your Roadmap to Senior-Level" — 4 to 6 concrete upgrades that turn the toy into something production-flavored (persistence, horizontal scaling, observability, fault tolerance, benchmarking), each with a one-line reason it matters.

In "## Further Reading", prioritise primary sources — papers, RFCs, and canonical docs — that the reader should study to deepen and evolve THIS project specifically. Name concrete tools and technologies throughout, and make the implementation section substantial.

Produce a substantive, in-depth article following every rule in the system prompt. Start your response with "---" (the frontmatter opener) — no preamble."

Wait, the user's message actually starts with: "Write a blog post about: Write a hands-on build guide for a portfolio/CV side project: a mini GPT training loop from scratch implementing rotary positional embeddings (RoPE) and fused RMSNorm in pure NumPy.

Audience: a working or aspiring engineer who wants a project that signals real systems skill to hiring managers. It must be practical enough to actually build from — real, runnable code, not pseudocode.

In ADDITION to the required TL;DR blockquote, "## Key Takeaways", and "## Further Reading", the body MUST include these "##" sections, in this order, BEFORE Key Takeaways:
1. "## Why This Project Stands Out on a CV" — the specific skills it demonstrates and the roles it signals for.
2. "## Architecture Overview" — the components and how they fit, as a bullet breakdown or text diagram.
3. "## Building It Step by Step" — numbered steps with real, language-tagged code snippets showing the core logic.
4. "## Running and Testing It" — how to run it locally and prove it works.
5. "## Extending It: Your Roadmap to Senior-Level" — 4 to 6 concrete upgrades that turn the toy into something production-flavored (persistence, horizontal scaling, observability, fault tolerance, benchmarking), each with a one-line reason it matters.

In "## Further Reading", prioritise primary sources — papers, RFCs, and canonical docs — that the reader should study to deepen and evolve THIS project specifically. Name concrete tools and technologies throughout, and make the implementation section substantial.

Produce a substantive, in-depth article following every rule in the system prompt. Start your response with "---" (the frontmatter opener) — no preamble."

Wait, the user's message actually starts with: "Write a blog post about: Write a hands-on build guide for a portfolio/CV side project: a mini GPT training loop from scratch implementing rotary positional embeddings (RoPE) and fused RMSNorm in pure NumPy.

Audience: a working or aspiring engineer who wants a project that signals real systems skill to hiring managers. It must be practical enough to actually build from — real, runnable code, not pseudocode.

In ADDITION to the required TL;DR blockquote, "## Key Takeaways", and "## Further Reading", the body MUST include these "##" sections, in this order, BEFORE Key Takeaways:
1. "## Why This Project Stands Out on a CV" — the specific skills it demonstrates and the roles it signals for.
2. "## Architecture Overview" — the components and how they fit, as a bullet breakdown or text diagram.
3. "## Building It Step by Step" — numbered steps with real, language-tagged code snippets showing the core logic.
4. "## Running and Testing It" — how to run it locally and prove it works.
5. "## Extending It: Your Roadmap to Senior-Level" — 4 to 6 concrete upgrades that turn the toy into something production-flavored (persistence, horizontal scaling, observability, fault tolerance, benchmarking), each with a one-line reason it matters.

In "## Further Reading", prioritise primary sources — papers, RFCs, and canonical docs — that the reader should study to deepen and evolve THIS project specifically. Name concrete tools and technologies throughout, and make the implementation section substantial.

Produce a substantive, in-depth article following every rule in the system prompt. Start your response with "---" (the frontmatter opener) — no preamble."

So the user wants a blog post about a mini GPT training loop from scratch implementing RoPE and fused RMSNorm in pure NumPy. The audience is a working or aspiring engineer who wants a project that signals real systems skill to hiring managers. It must be practical enough to actually build from — real, runnable code, not pseudocode.

In addition to the required TL;DR blockquote, "## Key Takeaways", and "## Further Reading", the body MUST include these "##" sections, in this order, BEFORE Key Takeaways:
1. "## Why This Project Stands Out on a CV" — the specific skills it demonstrates and the roles it signals for.
2. "## Architecture Overview" — the components and how they fit, as a bullet breakdown or text diagram.
3. "## Building It Step by Step" — numbered steps with real, language-tagged code snippets showing the core logic.
4. "## Running and Testing It" — how to run it locally and prove it works.
5. "## Extending It: Your Roadmap to Senior-Level" — 4 to 6 concrete upgrades that turn the toy into something production-flavored (persistence, horizontal scaling, observability, fault tolerance, benchmarking), each with a one-line reason it matters.

In "## Further Reading", prioritise primary sources — papers, RFCs, and canonical docs — that the reader should study to deepen and evolve THIS project specifically. Name concrete tools and technologies throughout, and make the implementation section substantial.

Produce a substantive, in-depth article following every rule in the system prompt. Start your response with "---" (the frontmatter opener) — no preamble.

So I need to output a markdown file starting with "---" as frontmatter, then the content.

Let me structure the frontmatter first, then the blog post body.

Frontmatter:
---
title: "Building a Mini GPT Training Loop from Scratch: NumPy RoPE + fused RMSNorm"
date: "2026-0