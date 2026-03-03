#!/usr/bin/env python3
"""Append an article to the LinkedIn posting queue with 2-hour spacing."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
META_FILE = REPO_ROOT / "data" / ".last_article_meta.json"
QUEUE_FILE = REPO_ROOT / "data" / "social_queue.json"


def load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def main() -> None:
    # Read article metadata written by generate_article.py
    if not META_FILE.exists():
        sys.exit(f"Error: {META_FILE} not found. Run generate_article.py first.")

    meta = load_json(META_FILE)
    title = meta.get("title", "")
    url = meta.get("url", "")
    social_hook = meta.get("social_hook", "")

    if not url:
        sys.exit("Error: article metadata missing 'url'.")

    # Read existing queue
    queue = load_json(QUEUE_FILE)
    if not isinstance(queue.get("posts"), list):
        queue = {"last_scheduled_at": None, "posts": []}

    now = datetime.now(timezone.utc)
    last_str = queue.get("last_scheduled_at")

    if last_str:
        last_dt = datetime.fromisoformat(last_str)
        candidate = last_dt + timedelta(hours=2)
        scheduled_at = max(now, candidate)
    else:
        scheduled_at = now

    # Skip if this URL is already pending (avoid double-queueing)
    existing_urls = {p["url"] for p in queue.get("posts", []) if p.get("status") == "pending"}
    if url in existing_urls:
        print(f"Already queued (pending): {url}")
        return

    entry = {
        "title": title,
        "url": url,
        "social_hook": social_hook,
        "scheduled_at": scheduled_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "pending",
    }

    queue["posts"].append(entry)
    queue["last_scheduled_at"] = entry["scheduled_at"]

    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Queued LinkedIn post for '{title}' at {entry['scheduled_at']}")


if __name__ == "__main__":
    main()
