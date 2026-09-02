#!/usr/bin/env python3
"""P3 — collect engagement (likes + comments) for posted LinkedIn entries.

For every queue entry that has a `post_urn`, calls the LinkedIn socialActions API
and writes {likes, comments, collected_at} back onto the entry as `stats`.

NOTE ON SCOPE: this captures likes/comments only. LinkedIn does NOT expose
impressions/reach for personal (member) posts via any API — that requires an
Organization page + Marketing Developer Platform approval. See docs/linkedin-api.md.

Usage:
    python scripts/collect_linkedin_stats.py            # collect + write back
    python scripts/collect_linkedin_stats.py --report   # print engagement ranking
    python scripts/collect_linkedin_stats.py --selftest  # run the aggregation self-check
"""

import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

QUEUE_PATH = Path(__file__).parent.parent / "data" / "social_queue.json"

# Generic framing words dropped when bucketing titles by topic (mirrors the
# worker's dedup tokenizer intent — keep the distinctive nouns).
STOPWORDS = {
    "the", "a", "an", "for", "with", "and", "to", "in", "of", "into", "on", "at",
    "from", "your", "you", "own", "via", "vs", "or", "as", "is", "are", "guide",
    "build", "building", "deep", "dive", "comprehensive", "production", "ready",
    "real", "world", "patterns", "practical", "modern", "scalable", "high",
    "performance", "using", "use", "zero", "hero", "basics", "architecture",
    "architecting", "mastering", "designing", "optimizing", "scaling",
    "implementing", "inside", "understanding", "systems", "system", "a",
}


def load_queue() -> dict:
    with open(QUEUE_PATH) as fh:
        return json.load(fh)


def save_queue(queue: dict) -> None:
    with open(QUEUE_PATH, "w") as fh:
        json.dump(queue, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def fetch_stats(urn: str, token: str) -> dict | None:
    """GET /v2/socialActions/{urn} -> {'likes': int, 'comments': int} or None."""
    encoded = urllib.parse.quote(urn, safe="")
    resp = requests.get(
        f"https://api.linkedin.com/v2/socialActions/{encoded}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  stats fetch failed for {urn}: {resp.status_code} {resp.text[:120]}")
        return None
    data = resp.json()
    likes = (data.get("likesSummary") or {}).get("totalLikes", 0)
    csum = data.get("commentsSummary") or {}
    comments = csum.get("count", csum.get("aggregatedTotalComments", 0))
    return {"likes": likes, "comments": comments}


def collect() -> None:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    if not token:
        sys.exit("Error: LINKEDIN_ACCESS_TOKEN not set")

    queue = load_queue()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = 0
    for entry in queue.get("posts", []):
        urn = entry.get("post_urn")
        if not urn or entry.get("status") != "posted":
            continue
        stats = fetch_stats(urn, token)
        if stats is None:
            continue
        entry["stats"] = {**stats, "collected_at": now}
        updated += 1
        time.sleep(0.3)  # ponytail: naive rate-limit; raise the sleep if we hit 429s
    save_queue(queue)
    print(f"Collected stats for {updated} posts.")


def title_tokens(title: str) -> set:
    toks = "".join(c.lower() if c.isalnum() else " " for c in title).split()
    return {t for t in toks if t not in STOPWORDS and not t.isdigit() and len(t) > 2}


def report(queue: dict | None = None) -> list:
    """Rank topic keywords by average engagement (likes+comments). Returns the
    ranked list so it's testable; also prints when called from the CLI."""
    queue = queue or load_queue()
    scored = [
        (e, e["stats"]["likes"] + e["stats"]["comments"])
        for e in queue.get("posts", [])
        if e.get("stats")
    ]
    # engagement summed per keyword, and post count per keyword -> average
    totals: dict = {}
    counts: dict = {}
    for entry, eng in scored:
        for kw in title_tokens(entry.get("title", "")):
            totals[kw] = totals.get(kw, 0) + eng
            counts[kw] = counts.get(kw, 0) + 1
    ranked = sorted(
        ((kw, totals[kw] / counts[kw], counts[kw]) for kw in totals if counts[kw] >= 3),
        key=lambda x: -x[1],
    )
    return ranked


def print_report() -> None:
    ranked = report()
    if not ranked:
        print("No stats collected yet — run without --report first (and give posts time).")
        return
    print(f"{'keyword':22} {'avg engagement':>14} {'posts':>7}")
    for kw, avg, n in ranked[:20]:
        print(f"{kw:22} {avg:14.1f} {n:7d}")


def selftest() -> None:
    q = {"posts": [
        {"title": "Mastering Kafka Partitioning", "stats": {"likes": 10, "comments": 2}},
        {"title": "Kafka Consumer Rebalancing Deep Dive", "stats": {"likes": 20, "comments": 0}},
        {"title": "Scaling Kafka Streams", "stats": {"likes": 6, "comments": 0}},
        {"title": "Vector Search Basics", "stats": {"likes": 1, "comments": 0}},
    ]}
    ranked = report(q)
    d = {kw: (avg, n) for kw, avg, n in ranked}
    # "kafka" appears in 3 posts -> qualifies (>=3); avg = (12+20+6)/3 = 12.67
    assert "kafka" in d, "kafka should qualify with 3 posts"
    assert abs(d["kafka"][0] - 12.6667) < 0.01, d["kafka"]
    # "vector" appears once -> excluded by the >=3 min-count guard
    assert "vector" not in d, "single-post keyword must be excluded"
    print("collect_linkedin_stats self-check passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--report" in sys.argv:
        print_report()
    else:
        collect()
