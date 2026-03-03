#!/usr/bin/env python3
"""Cron processor: post pending LinkedIn queue entries whose scheduled_at has passed."""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).parent.parent
QUEUE_FILE = REPO_ROOT / "data" / "social_queue.json"

# Poll settings: check article URL up to 5 min before giving up
POLL_INTERVAL_SECONDS = 10
POLL_MAX_SECONDS = 300


def load_queue() -> dict:
    if not QUEUE_FILE.exists():
        return {"last_scheduled_at": None, "posts": []}
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))


def save_queue(queue: dict) -> None:
    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


def poll_until_live(url: str) -> bool:
    """Return True if URL responds 200 within POLL_MAX_SECONDS."""
    deadline = time.time() + POLL_MAX_SECONDS
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                print(f"URL is live: {url}")
                return True
            print(f"Waiting for {url} (status {resp.status_code})...")
        except requests.RequestException as exc:
            print(f"Request error for {url}: {exc}")
        time.sleep(POLL_INTERVAL_SECONDS)
    print(f"Timed out waiting for {url}")
    return False


def main() -> None:
    # Import here so missing env vars don't crash at import time
    sys.path.insert(0, str(Path(__file__).parent))
    from post_to_linkedin import post_to_linkedin

    queue = load_queue()
    now = datetime.now(timezone.utc)
    posts_made = 0

    for entry in queue.get("posts", []):
        if entry.get("status") != "pending":
            continue

        scheduled_str = entry.get("scheduled_at", "")
        try:
            scheduled_dt = datetime.fromisoformat(scheduled_str)
        except ValueError:
            print(f"Invalid scheduled_at '{scheduled_str}', skipping.")
            continue

        if scheduled_dt > now:
            continue  # not yet due

        title = entry.get("title", "")
        url = entry.get("url", "")
        social_hook = entry.get("social_hook", "")
        tags = entry.get("tags", [])

        print(f"Processing: {title} ({url})")

        if not poll_until_live(url):
            print(f"Article not live yet, leaving as pending: {url}")
            continue

        try:
            post_to_linkedin(title=title, url=url, social_hook=social_hook, tags=tags)
            entry["status"] = "posted"
            posts_made += 1
            print(f"Posted to LinkedIn: {title}")
        except SystemExit as exc:
            print(f"LinkedIn post failed for '{title}': {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"Unexpected error posting '{title}': {exc}")

    save_queue(queue)
    print(f"Done. Posts made this run: {posts_made}")


if __name__ == "__main__":
    main()
