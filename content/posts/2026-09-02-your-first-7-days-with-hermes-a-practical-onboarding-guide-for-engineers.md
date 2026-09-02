---
title: "Your First 7 Days with Hermes: A Practical Onboarding Guide for Engineers"
date: "2026-09-02T15:51:20.519"
draft: false
tags: ["hermes", "onboarding", "developer-experience", "engineering-workflow", "knowledge-management"]
description: "A working engineer's day-by-day playbook for the first week with Hermes — from installation and indexing to daily capture rituals and team rollout."
summary: "A pragmatic, day-by-day onboarding guide for engineers adopting Hermes as a knowledge and context layer — covering setup, indexing, daily capture rituals, and team rollout."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-your-first-7-days-with-hermes-a-practical-onboarding-guide-for-engineers.svg"
  alt: "A stylised desk scene with a notebook, terminal, and a glowing index — representing a developer's first week organising knowledge with Hermes."
  caption: ""
  relative: false
---

> **TL;DR** — Hermes works best when you treat the first week as scaffolding, not heroics. Spend day one on installation and a clean inbox reset, days two and three on indexing your existing knowledge into graph-backed collections, days four and five on building a daily capture ritual, and days six and seven on team rollout with a shared taxonomy. By day eight, Hermes stops being "a new tool" and becomes your second brain.

## Why a week, not a day

Most engineers adopt new tools the way they adopt new linters: install it on a Friday, ignore it through the weekend, and forget which command launches the UI by Monday. Hermes doesn't reward that. It's a context layer — part personal wiki, part semantic index, part capture surface — and like any context layer, its value compounds only once you've seeded it with enough material that retrieval becomes meaningful.

Anecdotally, the engineers I've seen succeed with Hermes all describe the same arc: a clumsy first 48 hours, an "oh, it clicked" moment around day three or four, and a quiet dependency by the end of the week. This post is designed to compress that arc into seven deliberate days, so you can reach the inflection point by Wednesday and start shipping real value on Friday.

## Day 1 — Install, orient, and reset your inbox

Hermes ships as both a CLI and a desktop client. The CLI is the source of truth; the desktop app is a renderer over the same on-disk store. Install whichever fits your environment first — I'd recommend both.

```bash
# macOS / Linux
brew install hermes
# or, if you prefer the official installer
curl -fsSL https://get.hermes.dev | sh
```

Then verify and initialise:

```bash
hermes --version
hermes init ~/hermes-vault
hermes doctor
```

`hermes doctor` runs a battery of checks: disk permissions, index backend availability (it bundles a local [Tantivy](https://github.com/quickwit-oss/tantivy)-based search engine), and optional integration reachability (Git, Slack, Notion). Fix anything it flags before moving on.

The single most important thing you can do on day one is **reset your working memory**. Before you import anything, spend 20 minutes doing a brain dump of everything currently rattling around: half-finished design docs, the Slack thread you've been meaning to read, the bug you've been debugging for three days, the meeting notes from last week. Drop them into a `00-inbox/` folder inside your vault. Don't organise. Don't tag. Just capture.

This folder is your anti-bottleneck. Throughout the week you'll triage it, but the act of externalising it is what gives Hermes room to be useful — you can't search a brain, but you can search a folder.

### The mental model

Before touching more configuration, internalise three concepts:

1. **Collections** are semantic groupings of notes (a project, a system, an area of responsibility). They map roughly to tags but with structure.
2. **Edges** are typed relationships between notes (`depends-on`, `supersedes`, `related-to`). This is what makes Hermes feel graph-like rather than flat.
3. **Memories** are time-bound captures: meeting notes, quick thoughts, journal entries. They age out unless you promote them.

If you've used [Obsidian](https://obsidian.md) or [Logseq](https://logseq.com), this will feel familiar. If you're coming from Notion or Confluence, the shift is that Hermes is **local-first** — your vault is a folder of plain markdown files, and the index is a derivative cache.

## Day 2 — Index what you already have

Day two is bulk import. Hermes has first-class importers for the tools most engineers already live in:

```bash
# Import from a Git repo's docs, READMEs, and ADRs
hermes import git --repo ~/work/platform-team --path docs/

# Pull in a Notion workspace export
hermes import notion --export ./notion-export.zip

# Index a Slack channel's recent history
hermes import slack --channel engineering --days 90
```

What you import matters more than how much you import. A common first-week mistake is to dump your entire Google Drive or 40 GB of Slack history into Hermes and expect magic. The index will work; retrieval will be noisy. Instead, **import narrowly, then expand**:

- Start with one project repo's `docs/` directory.
- Add one Notion workspace or wiki.
- Index one or two high-signal Slack channels (think: incident reviews, design discussions, post-mortems).

Run the indexer once the imports land:

```bash
hermes index build --vault ~/hermes-vault
hermes index stats
```

The stats command will tell you how many notes were indexed, how many edges were inferred, and what the average note length is. Don't obsess over these numbers yet — but do note the total, because you'll compare against it on day seven to see how much you've grown the corpus organically.

### A note on embeddings

Hermes can run an embedding model locally for semantic search, but it doesn't enable it by default. On day two, turn it on only if your machine can handle it (16 GB RAM minimum, ideally an M-series Mac or a recent Linux box with AVX-512):

```bash
hermes config set embeddings.enabled true
hermes config set embeddings.model bge-small-en-v1.5
hermes embeddings build --vault ~/hermes-vault
```

The `bge-small-en-v1.5` model is a sensible default — fast, small (~130 MB), and good enough for retrieval over technical notes. If you're on weaker hardware, skip this on day two and revisit on day five once you've decided Hermes is sticking around.

## Day 3 — Build your first collection

By day three, the inbox is full of unsorted material. The temptation is to file everything. Resist. Instead, build **one** collection end-to-end so you can feel how the model works.

Pick a system you actually own. For me, it was our payment pipeline. For a friend, it was their on-call runbook. Pick something bounded — between 20 and 200 documents — so you can finish the work in an afternoon.

A collection in Hermes is a folder plus a manifest:

```text
collections/
  payments-platform/
    _collection.yaml
    notes/
      retry-semantics.md
      idempotency-keys.md
      stripe-webhook-failures.md
    edges.yaml
```

The `_collection.yaml` describes the collection's purpose, owner, and review cadence. The `edges.yaml` declares typed relationships between notes:

```yaml
edges:
  - from: retry-semantics.md
    to: idempotency-keys.md
    type: related-to
  - from: stripe-webhook-failures.md
    to: retry-semantics.md
    type: depends-on
```

Once this exists, Hermes' UI surfaces the collection as a navigable graph view. Click any note and you see its inbound and outbound edges, its tags, and its last-touched timestamp. This is the moment most engineers go "okay, I get it."

### What to put where

A useful heuristic: if a note would survive a reorganisation of your repo, it belongs in a collection. If it's tied to a specific incident, meeting, or sprint, it belongs in `00-inbox/` as a memory.

| Asset type | Destination | Why |
|---|---|---|
| ADRs, design docs, runbooks | `collections/<area>/notes/` | Long-lived, cross-referenced |
| Meeting notes, 1:1 logs | `journal/YYYY-MM-DD.md` | Time-bound, ephemeral |
| Slack threads worth keeping | `collections/<area>/threads/` | Searchable but contextualised |
| Random thoughts, TODOs | `00-inbox/` | Captured but not yet committed |

## Day 4 — Establish the capture ritual

Day four is where most onboarding plans go soft. You've installed, indexed, and built one collection. Now you need to make Hermes a daily habit, and habits are built in tiny increments.

Pick a **single capture surface** and commit to it for the week. The most common options:

- **CLI**: `hermes note "subject" --body "..."` — best for terminal-native engineers.
- **Global hotkey**: bind `Cmd+Shift+H` to "Quick capture" — best for capturing during meetings.
- **Browser extension**: clip highlights and snippets into a named buffer — best for research-heavy work.

I'd recommend the CLI plus the hotkey. The CLI gives you a fast path during focused work; the hotkey catches the stray thoughts that would otherwise evaporate.

Then schedule a **10-minute daily review**. Mine runs at 4:50pm, five minutes before I stop for the day:

1. Open `00-inbox/`.
2. For each item, decide: file it, promote it to a collection, link it to an existing note, or delete it.
3. Anything that survived gets a collection destination and at least one edge.

This sounds trivial, but it's the single most important habit you can build. Tools like [Are.na](https://are.na) and [Readwise](https://readwise.io) succeed for the same reason — they force a tiny, repeatable ritual that keeps the corpus honest.

### Patterns in production

The teams I know who have the highest Hermes retention all share one pattern: **the daily review is non-negotiable and calendar-protected**. It's not "I'll do it if I have time." It's a 10-minute block that ships every day, the same way standups ship.

A second pattern: **capture is permissionless, promotion is gated**. Anyone on the team can drop a memory into `00-inbox/`. Promoting a memory into a collection requires the collection owner's review. This keeps the index clean without bottlenecking capture.

## Day 5 — Wire up your editor

By day five, you should be capturing into Hermes several times a day. The next friction point is editing. Hermes stores notes as markdown, so any editor works, but the experience is much better if you wire up bidirectional linking and a live preview.

For [VS Code](https://code.visualstudio.com/), the `Hermes Companion` extension handles this. Install it, point it at your vault, and enable:

- **Wiki-link autocompletion**: typing `[[` suggests existing note titles.
- **Backlink panel**: shows every other note that links to the current one.
- **Edge hints**: surfaces declared edges in the gutter.

For [Neovim](https://neovim.io/), the setup is more manual but powerful — `vim-markdown` plus a small Lua snippet that calls `hermes link suggest` on `<C-x><C-u>` works well.

Whichever editor you choose, enable **autosave**. Hermes indexes on file change, and there's no value in batching saves — the index is incremental and cheap.

## Day 6 — Roll out to the team

Day six is where the value multiplies. Hermes is genuinely useful solo, but it's transformative when a team shares a vault or a federated set of collections.

Start with **two collaborators, not twenty**. Pick a teammate who works on an adjacent system and propose a shared collection. A good first shared collection is something cross-cutting that neither of you fully owns: an incident response playbook, a vendor comparison, an onboarding guide for new hires.

```bash
hermes team invite --collection payments-platform alice@company.com
hermes team grant --collection payments-platform --role editor alice@company.com
```

Roles matter more than you'd think. Hermes has three: viewer, editor, owner. Default to **editor** for active collaborators and **viewer** for stakeholders who should see but not modify. Reserve owner for the person accountable for the collection's hygiene.

Once the team is wired up, establish a **shared taxonomy**. This is the unsexy work that determines whether the rollout sticks. Agree on:

- **Collection names**: kebab-case, scoped to the system or area.
- **Edge types**: a short, fixed vocabulary (`depends-on`, `supersedes`, `related-to`, `blocks`, `references`).
- **Tag prefixes**: e.g., `team:payments`, `severity:p1`, `status:draft`. Prefixes make tags sortable and filterable.

Document these in a `CONTRIBUTING.md` at the vault root and link it from your team's main runbook. This is the kind of friction that pays for itself within a week.

### Architecture: how the team mode works

Under the hood, Hermes team mode is a [CRDT](https://en.wikipedia.org/wiki/Conflict-free_replicated_data_type)-backed sync layer over your local vault. Each collaborator runs a local Hermes daemon; changes propagate through a relay server (self-hosted or managed) and merge deterministically on every peer. Edits are attributed, deletions are tombstones, and the index is rebuilt locally on each peer.

This is worth knowing because it explains the operational characteristics:

- **Offline-first**: edits made without network connectivity sync when connectivity returns.
- **Eventually consistent**: you might see your own change before a teammate sees it, and vice versa, but convergence is guaranteed.
- **Append-mostly**: the model is optimised for note creation and linking, not for in-place rewriting of large documents. Treat notes as immutable once they're "done" and create a successor note rather than rewriting.

## Day 7 — Review, prune, and plan

You've been using Hermes for a week. Time to find out if it's working.

```bash
hermes report weekly --vault ~/hermes-vault
```

The weekly report gives you four numbers that matter:

1. **Notes created**: how much you captured.
2. **Edges created**: how much you connected.
3. **Searches performed**: how often you used Hermes for retrieval.
4. **Memories promoted**: how many inbox items graduated to collections.

If your "notes created" is high and your "searches performed" is low, you're capturing more than you're retrieving — a sign your retrieval patterns need work. If "memories promoted" is near zero, your inbox is filling up and the daily review isn't happening.

Compare your index stats from day two to now:

```bash
hermes index stats --compare ~/hermes-vault/.hermes/snapshot-day2.json
```

You should see double-digit percent growth in note count, edge count, and embedding coverage if embeddings are enabled.

### A pruning ritual

Once a week, do a 20-minute **collection pruning session**. For each collection, ask:

- Are there notes nobody has touched in 90 days? Archive them.
- Are there edges that no longer reflect reality? Delete them.
- Are there tags or edge types that have proliferated? Consolidate them.

Hermes makes this easy:

```bash
hermes collection lint --collection payments-platform
hermes collection prune --collection payments-platform --older-than 90d --dry-run
hermes collection prune --collection payments-platform --older-than 90d
```

The `--dry-run` flag is your friend. Always preview before deleting.

## Key Takeaways

- **Day one is reset, not install.** Empty your head into `00-inbox/` before you configure anything else.
- **Import narrowly, then expand.** A focused corpus retrieves better than a complete one.
- **Build one collection end-to-end.** Feeling the model is worth more than reading the docs.
- **The daily review is the habit.** Ten minutes, calendar-protected, every day.
- **Capture is permissionless, promotion is gated.** This keeps the index clean without bottlenecking the team.
- **Editor integration is force-multiplied.** Wire up backlinks, autocompletion, and autosave from day five onward.
- **Prune weekly.** A small collection you trust beats a large one you don't.

## Further Reading

- [Hermes official documentation — Getting Started](https://hermes.dev/docs/getting-started)
- [The case for local-first software — Ink & Switch](https://www.inkandswitch.com/local-first/)
- [Tantivy — the full-text search engine that powers Hermes indexing](https://github.com/quickwit-oss/tantivy)
- [Obsidian's guide to bidirectional linking](https://help.obsidian.md/links)
- [Andy Matuschak's notes on evergreen note-taking](https://notes.andymatuschak.org/Evergreen_notes)
- [Logseq — an open-source outliner with similar graph semantics](https://logseq.com)