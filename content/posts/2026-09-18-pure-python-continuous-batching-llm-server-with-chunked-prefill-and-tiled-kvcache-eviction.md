We need to generate a complete markdown file following all the rules. Let's break down the requirements.

First, frontmatter: starting with "---" on its own line, then fields. Must include title, date, draft, tags, description, summary, showToc, TocOpen, cover. The cover.image must be "/images/covers/2026-09-18-pure-python-continuous-batching-llm-server-with-chunked-prefill-and-tiled-kvcache-eviction.svg". The title must be appropriate. date fixed to "2026-09-18T19:01:33.052". tags: 3-6 relevant tags, each in double quotes, JSON-style array. We'll pick tags like "python", "llm", "caching", "server", "hvac"? Actually relevant: "python", "llm", "caching", "server". Maybe 5 tags.

Frontmatter must not be wrapped in code fences. Must start with "---". And after frontmatter, the body.

We need to ensure we don't wrap frontmatter in code fences. So output starts:

---
title: "Pure-Python Continuous-Batching LLM Server with Chunked Prefill and Tiled KV‑Cache Eviction"
date: "2026-09-18T19:01:33.052"
draft: false
tags: ["python", "llm", "caching", "server", "performance"]
description: "Build a production‑style LLM inference server in pure Python using chunked prefill, token‑level scheduling and a tiled KV‑cache eviction strategy — a hands‑on project that signals systems engineering skill to hiring managers."
summary: "A complete guide to building a pure‑Python continuous‑batch LLM server with chunked prefill, token‑level scheduling and tiled KV‑cache eviction, ready to run and extend."
showToc: true
TocOpen: false
cover:
  image: "__COVER_PATH__"
  alt: "A sleek Python LLM server running on a developer laptop"
  caption: ""
  relative: false

Now body. Must follow structure:

1. TL;DR blockquote as very first body block:
   > **TL;DR** — 2–3 sentences capturing the key insight of the post.

So after frontmatter, first thing is:

> **TL;DR** — ... (2-3 sentences)

We need to ensure it's a blockquote starting with >. And it must be the very first body block. So after frontmatter, first characters should be >.

2. A brief intro paragraph (no heading needed). So after TL;DR blockquote, a paragraph.

3. Main sections using "## Section Title" (H2). Use "### Subsection" (H3) for nesting. Never use H1 in the body.

We need sections:

- "## Why This Project Stands Out on a CV"
- "## Architecture Overview"
- "## Building It Step by Step"
- "## Running and Testing It"
- "## Extending It: Your Roadmap to Senior-Level"
- Then "## Key Takeaways" (penultimate)
- Then "## Further Reading" (final)

We also need to ensure that there is no "# Heading" repeating title. So we must not have "# " anywhere.

Now content specifics.

We need to include code snippets with language tags. Implementation steps must have real, language-tagged code snippets showing core logic.

Also need to follow content rules: every fenced code block must include a language tag. When citing a source, use real inline markdown link at point of claim, no bracketed-number citations.

We need bullet points and numbered lists. Use blockquotes for noteworthy asides.

We need to keep professional but accessible tone.

We need at least 1800-2600 words. Aim for substantive. We'll try to be concise but thorough, maybe around 2000 words.

Now we need to design each section.

Section 1: Why This Project Stands Out on a CV. Talk about skills: systems design, concurrency, memory management, Python performance, LLM serving, etc. Signals roles: backend engineer, infra, AI/ML engineer, data platform.

Section 2: Architecture Overview. Provide bullet breakdown or text diagram. Components: HTTP API server (maybe using FastAPI or Flask), request parser, batcher with chunked prefill, token-level scheduler, tiled KV-cache eviction, worker threads/processes, maybe using asyncio, GIL considerations. Provide diagram.

Section 3: Building It Step by Step. Numbered steps with code snippets. We'll need to provide real runnable code. Could show minimal server using FastAPI, a batching loop, chunked prefill logic (grouping tokens into chunks), token-level scheduling (maybe a priority queue), tiled KV-cache eviction (fixed-size tiles, LRU). Provide snippets.

Step examples:

Step 1: Install dependencies, set up project structure.

Step 2: Define the KV cache tile structure.

Step 3: Implement chunked prefill function.

Step 4: Token-level scheduler.

Step 5: Assemble server with FastAPI endpoints.

We need to ensure code fenced with ```python etc.

Section 4: Running and Testing It. How to run locally, maybe using uvicorn, test with curl or a simple client script, show output.

Section 5: Extending It: Your Roadmap to Senior-Level. 4-6 concrete upgrades: persistence (Redis or RocksDB), horizontal scaling (using message queue like RabbitMQ or gRPC), observability (Prometheus metrics, OpenTelemetry), fault tolerance (circuit breaker, retry), benchmarking (using LLama benchmark), etc. Each with one-line reason.

Further Reading: prioritize primary sources: papers (e.g., "Continuous Batching for LLM Serving" maybe "A Survey of KV-Cache Eviction", "FlashAttention", "vLLM" docs, "TensorRT-LLM", "KVCache eviction policies". Also canonical docs: vLLM docs, FastAPI, asyncio. Provide at least 3 real URLs.

Now ensure that we have bullet points and numbered lists where appropriate.

We must avoid any code fences outside body? Actually code fences are allowed inside body, but not wrapping frontmatter. So we can have fenced code blocks.

We need to ensure that we have no trailing ellipsis in description? The rule: description: "140–160 character SEO meta description, complete sentences, no trailing ellipsis." So we need a description between 140-160 characters, complete sentences, no trailing ellipsis. Let's count characters. We'll produce something like: "Build a pure‑Python LLM inference server with chunked prefill, token‑level scheduling and tiled KV‑cache eviction. Hands‑on guide, runnable code, signals systems skill." Let's count: We'll aim for around 150 chars. We'll ensure no trailing ellipsis.

Summary: one or two sentences that will appear on listing pages and in social cards. We'll give two sentences.

Now tags: JSON-style array with each tag in double quotes. Provide 5 tags: "python", "llm", "caching", "server", "performance". Ensure they are double quoted and separated by commas, no extra spaces? It's okay.

Now frontmatter: date fixed.

Now ensure that after frontmatter we start with ">" for TL;DR blockquote. The very first characters of response must be "---". Already done.

Now we need to ensure we have the TL;DR blockquote as the very first body block. So after the frontmatter closing "---"? Actually frontmatter ends with "---"? Actually frontmatter is a YAML block enclosed by "---" at start and end. The rule: "The very first characters of your response MUST be "---" on its own line. No preamble, no explanation, no "Here is your blog post:"." So we start with "---". Then frontmatter fields. Then after the final "---" of frontmatter, the body starts. Usually in Hugo, frontmatter is at top between two "---" lines. So we need to output:

---
title: "..."
...
---
> **TL;DR** ...

Thus after the second "---" (closing frontmatter), the body starts. That matches typical markdown frontmatter. The rule says "The very first characters of your response MUST be "---" on its own line." So we start with "---". Then we have frontmatter content. Then we need a closing "---"? The typical frontmatter format has a closing "---". The rule about frontmatter format says: "emit EXACTLY this shape, filling in the values:" then they show:

---
title: "Your Title Here"
date: "2026-09-18T19:01:33.052"
draft: false
tags: ["tag1", "tag2", "tag3", "tag4", "tag5"]
description: "140–160 character SEO meta description, complete sentences, no trailing ellipsis."
summary: "One or two sentences that will appear on listing pages and in social cards."
showToc: true
TocOpen: false
cover:
  image: "__COVER_PATH__"
  alt: "Short description of the cover image subject."
  caption: ""
  relative: false
---

So they include a closing "---" on its own line after the cover relative field. So we must output exactly that, with the closing "---". So after that, the body begins.

Thus structure:

---
title: "..."
...
---
> **TL;DR** ...

So after the closing "---", the next line is the TL;DR blockquote. Good.

Now ensure we have no extra spaces before the ">"? It's okay.

Now we need to produce a substantive article. We'll need to count words. We'll aim for ~2000 words. We'll have sections with enough detail.

Now some specifics:

- In "## Why This Project Stands Out on a CV", we need to mention specific skills: Python performance optimization, async I/O, memory management, KV-cache design, concurrency, batching, etc. Also roles: backend engineer, AI infrastructure, data platform, ML ops.

- "## Architecture Overview": bullet breakdown or text diagram. We'll use a text diagram with arrows, maybe using mermaid? But mermaid may be considered a code block? Possibly we can embed as a code block with language none, but better to just use plain text diagram. We'll avoid fenced code blocks for diagram? The rule says "Every fenced code block MUST include a language tag: ```python, ```bash, etc. Never bare ```." So we can have a fenced code block with language "text" or "mermaid"? But mermaid might not be recognized; better to use language "text". But we can also just use a bullet list describing components. We'll do a bullet breakdown.

But we may want to include a text diagram like:

```
API (FastAPI) --> Batcher (chunked prefill) --> Token Scheduler --> KV Cache (tiled) --> LLM Engine (e.g., transformers)
```

But that would be a code block if we wrap in ```. We could just write as plain text without fences. That's fine.

- "## Building It Step by Step": numbered steps with real code snippets. We'll provide maybe 7 steps, each with a code snippet labeled ```python.

Make sure each code snippet is complete but minimal. Provide necessary imports.

- "## Running and Testing It": instructions: install dependencies, run with uvicorn, test endpoint with curl, maybe show sample JSON response.

- "## Extending It: Your Roadmap to Senior-Level": 4-6 upgrades, each with one-line reason.

- "## Key Takeaways": 3-6 bullet points summarizing.

- "## Further Reading": at least 3 real URLs, prioritize primary sources: papers, RFCs, canonical docs. Provide descriptive anchor text and URL.

Now ensure we have no H1 in body. We have "##" headings which are H2. That's fine.

Now check for any repeated title as "# Heading". We won't have that.

Now ensure we have bullet points and numbered lists.

Now ensure code fences have language tags.

Now ensure we don't have bracketed-number citations. We'll use inline links like "[the Celery docs](https://docs.celeryq.dev)" but we might not need citations unless we reference something. We can reference "vLLM" docs: "[vLLM design doc](https://github.com/vllm/vllm)". That's okay.

Now ensure the description length. Let's compute description characters.

We need 140-160 characters, complete sentences, no trailing ellipsis.

Let's craft: "Build a pure‑Python LLM inference server with chunked prefill, token‑level scheduling and a tiled KV‑cache eviction strategy. This hands‑on guide provides runnable code and signals systems engineering skill to hiring managers."

Count characters: Let's count manually.

"Build a pure‑Python LLM inference server with chunked prefill, token‑level scheduling and a tiled KV‑cache eviction strategy. This hands‑on guide provides runnable code and signals systems engineering skill to hiring managers."

Count characters including spaces and punctuation.

I'll quickly approximate: 
"Build a pure‑Python LLM inference server with chunked prefill, token‑level scheduling and a tiled KV‑cache eviction strategy." That's sentence 1 length maybe ~120? Let's count precisely later. But we need total 140-160 including second sentence.

Second sentence: "This hands‑on guide provides runnable code and signals systems engineering skill to hiring managers." That's maybe ~80 characters. Combined maybe ~200, too long. Need to reduce.

We need 140-160 total. So maybe make each sentence shorter.

Let's craft: "Build a pure‑Python LLM inference server with chunked prefill, token‑level scheduling and a tiled KV‑cache eviction strategy. This hands‑on guide provides runnable code and signals systems engineering skill to hiring managers."

Count characters: Let's count using rough method.

First sentence: "Build a pure‑Python LLM inference server with chunked prefill, token‑level scheduling and a tiled KV‑cache eviction strategy."

Count characters: I'll count each character including spaces.

We'll write it out:

B u i l d (5) + space (1) =6
a (1) + space =2 =>8
p u r e‑ (pure‑ includes hyphen?) Actually "pure‑Python" maybe with en dash? We'll just use "pure-Python". So "pure-Python" length 12? Let's just count as characters.

Better to use a character counter, but we can approximate. Let's maybe produce a description of exactly 150 characters. We'll craft manually and then count.

Potential description: "Build a pure-Python LLM inference server with chunked prefill, token-level scheduling and a tiled KV-cache eviction strategy. This hands-on guide offers runnable code and signals systems‑engineering skill to hiring managers."

Now count.

First sentence: "Build a pure-Python LLM inference server with chunked prefill, token-level scheduling and a tiled KV-cache eviction strategy."

Let's count:

"Build" (5)
space (1) =6
"a" (1) =7
space =8
"pure-Python" (12) includes hyphen and Python 8 letters? Actually "pure-Python" = 4 + 1 hyphen + 7 =12. So =20
space =21
"LLM" (3) =24
space =25
"inference" (9) =34
space =35
"server" (6) =41
space =42
"with" (4) =46
space =47
"chunked" (7) =54
space =55
"prefill," (8 including comma) =63
space =64
"token-level" (11 including hyphen) =75
space =76
"scheduling" (10) =86
space =87
"and" (3) =90
space =91
"a" (1) =92
space =93
"tiled" (5) =98
space =99
"KV-cache" (8) including hyphen? "KV-cache" 8 =107
space =108
"eviction" (8) =116
space =117
"strategy." (9 including period) =126

So first sentence 126 characters.

Second sentence: "This hands-on guide offers runnable code and signals systems‑engineering skill to hiring managers."

Count:

"This" (4) =1? Actually start count from beginning: we add to total.

Let's count second sentence characters: "This" (4)
space (1) =5
"hands-on" (8) including hyphen =13
space =14
"guide" (5) =19
space =20
"offers" (6) =26
space =27
"runnable" (8) =35
space =36
"code" (4) =40
space =41
"and" (3) =44
space =45
"signals" (7) =52
space =53
"systems‑engineering" maybe "systems-engineering" 18? Let's count: "systems-engineering" = "systems" (7) + hyphen (1) + "engineering" (10) =18. So add 18 =>71
space =72
"skill" (5) =77
space =78
"to" (2) =80
space =81
"hiring" (6) =87
space =88
"managers." (9 including period) =97

So second sentence 97 characters.

Total 126 + 97 = 223, too long. Need 140-160 total. So we need much shorter description.

We need description 140-160 characters total, including both sentences. So maybe just one sentence of 150 characters, or two shorter sentences summing to 150.

Let's aim for one sentence of about 150 characters, no trailing ellipsis. Or two sentences sum to 150.

Simplify: "Build a pure-Python LLM inference server with chunked prefill, token-level scheduling and a tiled KV-cache eviction strategy. This hands-on guide delivers runnable code and signals systems‑engineering skill to hiring managers."

Now count.

First sentence same as before 126 characters. Second sentence: "This hands-on guide delivers runnable code and signals systems‑engineering skill to hiring managers."

Count second: "This" (4)
space (1) =5
"hands-on" (8) =13
space =14
"guide" (5) =19
space =20
"delivers" (8) =28
space =29
"runnable" (8) =37
space =38
"code" (4) =42
space =43
"and" (3) =46
space =47
"signals" (7) =54
space =55
"systems‑engineering" (18) =73
space =74
"skill" (5) =79
space =80
"to" (2) =82
space =83
"hiring" (6) =89
space =90
"managers." (9) =99

So second sentence 99 characters. Total 126+99=225 still too long.

We need to reduce first sentence length drastically. Maybe drop some words.

Goal: total 150 characters. Let's aim for 150 total. So maybe first sentence 80 chars, second 70 chars.

Let's craft a concise description: "Build a pure-Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction. This hands‑on guide gives runnable code and signals systems‑engineering skill to hiring managers."

Now count.

First sentence: "Build a pure-Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction."

Count:

"Build" (5)
space (1)=6
"a"(1)=7
space=8
"pure-Python"(12)=20
space=21
"LLM"(3)=24
space=25
"server"(6)=31
space=32
"with"(4)=36
space=37
"chunked"(7)=44
space=45
"prefill,"(8)=53
space=54
"token-level"(11)=65
space=66
"scheduling"(10)=76
space=77
"and"(3)=80
space=81
"tiled"(5)=86
space=87
"KV‑cache"(8)=95
space=96
"eviction."(9)=105

So first sentence 105 characters.

Second sentence: "This hands‑on guide gives runnable code and signals systems‑engineering skill to hiring managers."

Count:

"This"(4)
space=5
"hands‑on"(8)=13
space=14
"guide"(5)=19
space=20
"gives"(5)=25
space=26
"runnable"(8)=34
space=35
"code"(4)=39
space=40
"and"(3)=43
space=44
"signals"(7)=51
space=52
"systems‑engineering"(18)=70
space=71
"skill"(5)=76
space=77
"to"(2)=79
space=80
"hiring"(6)=86
space=87
"managers."(9)=96

Second sentence 96 characters.

Total 105+96=201, still over 160.

We need to cut more. Maybe make both sentences shorter, maybe just one sentence of ~150 chars.

Let's try a single sentence: "Build a pure-Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction; this hands‑on guide gives runnable code and signals systems‑engineering skill to hiring managers."

But we need no trailing ellipsis; a semicolon is fine. But we need a single sentence? The description can be one sentence or two sentences but total characters 140-160.

Let's try a single sentence of about 150 characters.

"Build a pure-Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction; this hands‑on guide gives runnable code and signals systems‑engineering skill to hiring managers."

Now count characters.

We'll count manually.

String: "Build a pure-Python LLM server with chunked? Wait re-evaluate.

Let's write it clearly:

Build a pure-Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction; this hands‑on guide gives runnable code and signals systems‑engineering skill to hiring managers.

Now count.

I'll number characters:

1 B
2 u
3 i
4 l
5 d
6 space
7 a
8 space? Actually after "Build" there is space. So position 6 space.

Let's just count using groups.

"Build" =5
space =1 =>6
"a" =1 =>7
space =>8
"pure-Python" =12 =>20
space =>21
"LLM" =3 =>24
space =>25
"server" =6 =>31
space =>32
"with" =4 =>36
space =>37
"chunked" =7 =>44
space =>45
"prefill," =8 (including comma) =>53
space =>54
"token-level" =11 =>65
space =>66
"and" =3 =>69
space =>70
"tiled" =5 =>75
space =>76
"KV‑cache" =8 =>84
space =>85
"eviction;" =9 (including semicolon) =>94
space =>95
"this" =4 =>99
space =>100
"hands‑on" =8 =>108
space =>109
"guide" =5 =>114
space =>115
"gives" =5 =>120
space =>121
"runnable" =8 =>129
space =>130
"code" =4 =>134
space =>135
"and" =3 =>138
space =>139
"signals" =7 =>146
space =>147
"systems‑engineering" =18 =>165
space =>166
"skill" =5 =>171
space =>172
"to" =2 =>174
space =>175
"hiring" =6 =>181
space =>182
"managers." =9 =>191

Total 191 characters, too high.

We need 140-160. So we need to cut about 30-50 characters.

Maybe remove some words, shorten phrase.

Try: "Build a pure-Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction. This hands‑on guide gives runnable code and signals systems‑engineering skill to hiring managers."

Now count.

First sentence: "Build a pure-Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction."

We earlier counted similar sentence as 105 characters. Let's recount quickly.

"Build"5, space1=6, "a"1=7, space=8, "pure-Python"12=20, space=21, "LLM"3=24, space=25, "server"6=31, space=32, "with"4=36, space=37, "chunked"7=44, space=45, "prefill,"8=53, space=54, "token-level"11=65, space=66, "and"3=69, space=70, "tiled"5=75, space=76, "KV‑cache"8=84, space=85, "eviction."9=94.

So first sentence 94 characters.

Second sentence: "This hands‑on guide gives runnable code and signals systems‑engineering skill to hiring managers."

We counted earlier 96 characters.

Total 94+96=190, still over.

We need total 150. So we need to cut about 40 characters. Maybe shorten both sentences significantly.

Maybe use only one sentence of about 150 chars. Let's try a single sentence of about 150 chars.

"Build a pure-Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction; this guide gives runnable code and signals systems‑engineering skill to hiring managers."

Now count.

We'll count characters.

String: "Build a pure-Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction; this guide gives runnable code and signals systems‑engineering skill to hiring managers."

Let's count.

"Build"5
space1=6
"a"1=7
space=8
"pure-Python"12=20
space=21
"LLM"3=24
space=25
"server"6=31
space=32
"with"4=36
space=37
"chunked"7=43? Wait we had 44 earlier; let's recount: after space, "chunked" 7 characters => 37+7=44. Actually we had 37 then +7 =44. okay.

space=45
"prefill,"8=53
space=54
"token-level"11=65
space=66
"and"3=69
space=68? Actually after "and" we have space => 70? Let's keep track systematically.

I'll rewrite with indices:

1-5 "Build"
6 space
7 "a"
8 space
9-20 "pure-Python" (12 chars) => positions 9-20
21 space
22-24 "LLM" (3) => positions 22-24
25 space
26-31 "server" (6) => positions 26-31
32 space
33-36 "with" (4) => positions 33-36
37 space
38-44 "chunked" (7) => positions 38-44
45 space
46-53 "prefill," (8) => positions 46-53
54 space
55-65 "token-level" (11) => positions 55-65
66 space
67-69 "and" (3) => positions 67-69
70 space
71-75 "tiled" (5) => positions 71-75
76 space
77-84 "KV‑cache" (8) => positions 77-84
85 space
86-94 "eviction;" (9) => positions 86-94 (including semicolon)
95 space
96-99 "this" (4) => positions 96-99
100 space
101-108 "guide" (5) => positions 101-108? Actually "guide" 5 chars => 101-105, but let's compute: after space at 100, next chars: "guide" 5 => positions 101-105.
106 space
107-111 "gives" (5) => positions 107-111
112 space
113-120 "runnable" (8) => positions 113-120
121 space
122-125 "code" (4) => positions 122-125
126 space
127-129 "and" (3) => positions 127-129
130 space
131-137 "signals" (7) => positions 131-137
138 space
139-156 "systems‑engineering" (18) => positions 139-156
157 space
158-162 "skill" (5) => positions 158-162
163 space
164-165 "to" (2) => positions 164-165
166 space
167-172 "hiring" (6) => positions 167-172
173 space
174-182 "managers." (9) => positions 174-182

Total characters = 182. Still over 160.

We need to cut down to max 160. So we need to reduce about 22 characters.

We can shorten some words: maybe drop "pure-Python" to "Python". Or drop "systems‑engineering". Or shorten phrase.

Let's try a more concise description: "Build a Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction. This guide gives runnable code and signals engineering skill to hiring managers."

Now count.

First sentence: "Build a Python LLM server with chunked prefill, token-level scheduling and tiled KV‑cache eviction."

Count:

"Build"5
space1=6
"a"1=7
space=8
"Python"6=14
space=15
"LLM"3=18
space=19
"server"6=25
space=26
"with"4=30
space=31
"chunked"7=38
space=39
"prefill,"8=47
space=48
"token-level"11=59
space=60
"and"3=63
space=64
"tiled"5=69
space=70
"KV‑cache"8=78
space=79
"eviction."9=88

First sentence 88 characters.

Second sentence: "This guide gives runnable code and signals engineering skill to hiring managers."

Count:

"This"4
space1=5
"guide"5=10
space=11
"gives"5=16
space=17
"runnable"8=25
space=26
"code"4=30
space=31
"and"3=34
space=35
"signals"7=42
space=43
"engineering"11=54
space=55
"skill"5=60
space=61
"to"2=63
space=64
"hiring"6=70
space=71
"managers."9=80

Second sentence 80 characters.

Total 88+80=168, still over 160 by 8.

We need total 140-160. So we need to reduce total by at least 9 characters. We can shorten second sentence maybe "This guide gives runnable code and signals engineering skill to hiring managers." That's 78? Let's count.

Second sentence revised: "This guide gives runnable code and signals engineering skill to hiring managers."

Count:

"This"4
space1=5
"guide"5=10
space=11
"gives"5=16
space=17
"runnable"8=25
space=26
"code"4=30
space=31
"and"3=34
space=35
"signals"7=42
space=43
"engineering"11=54
space=55
"skill"5=60
space=61
"to"2=63
space=64
"hiring"6=70
space=71
"managers."9=80

Actually same 80? Wait we have "engineering" vs earlier "engineering skill". It's same length. Maybe we can drop "engineering". Use "skill". Let's try: "This guide gives runnable code and signals skill to hiring managers."

Count:

"This"4
space1=5
"guide"5=10
space=11
"gives"5=16
space=17
"runnable"8=25
space=26
"code"4=30
space=31
"and"3=34
space=35
"sign