#!/usr/bin/env python3
"""Local CLI helper to schedule an article for future generation.

Usage:
    python scripts/queue_article.py "GraphQL Zero to Hero" --delay 2h
    python scripts/queue_article.py "Redis Tutorial" --delay 30m
    python scripts/queue_article.py "Rust Basics" --delay 5m
    python scripts/queue_article.py "Immediate Article"   # no delay → now
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

QUEUE_FILE = Path("data/article_queue.json")


def parse_delay(delay_str: str) -> timedelta:
    """Parse delay strings like '2h', '30m', '1h30m', '5s'."""
    pattern = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")
    m = pattern.fullmatch(delay_str.strip().lower())
    if not m or not any(m.groups()):
        sys.exit(f"Invalid delay format '{delay_str}'. Use e.g. '2h', '30m', '1h30m'.")
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add an article to the generation queue."
    )
    parser.add_argument("topic", help="Article topic / prompt")
    parser.add_argument(
        "--delay",
        default="0m",
        help="Delay before publish (e.g. '2h', '30m', '1h30m'). Default: now.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Don't git commit + push after adding to queue.",
    )
    args = parser.parse_args()

    delay = parse_delay(args.delay)
    publish_after = (datetime.now(timezone.utc) + delay).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load existing queue
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if QUEUE_FILE.exists():
        queue = json.loads(QUEUE_FILE.read_text())
    else:
        queue = []

    entry = {
        "topic": args.topic,
        "publish_after": publish_after,
        "status": "pending",
    }
    queue.append(entry)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2) + "\n")

    print(f"Queued: '{args.topic}' — will publish after {publish_after}")

    if not args.no_push:
        subprocess.run(["git", "add", str(QUEUE_FILE)], check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Queue: add '{args.topic}' (publish after {publish_after})"],
            check=True,
        )
        subprocess.run(["git", "push"], check=True)
        print("Committed and pushed. The cron job will pick it up within 30 minutes.")


if __name__ == "__main__":
    main()
