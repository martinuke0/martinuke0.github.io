#!/usr/bin/env python3
"""Cron processor: post pending LinkedIn queue entries whose scheduled_at has passed.

Dup-proof by design (at-most-once). Each entry is CLAIMED — marked "posting" and
committed to git — BEFORE the LinkedIn API call. Once that claim lands, no other
run will ever see the entry as "pending", so it can never be posted twice. Every
failure path degrades to a MISS (surfaced, not silent), never a duplicate:

    pending --claim(commit)--> posting --post ok--> posted
                                       \\--API reject--> pending (safe retry; not posted)
                                       \\--ambiguous / crash--> stays "posting" (never reposted)
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).parent.parent
QUEUE_FILE = REPO_ROOT / "data" / "social_queue.json"

POLL_INTERVAL_SECONDS = 10
POLL_MAX_SECONDS = 300


def load_queue() -> dict:
    if not QUEUE_FILE.exists():
        return {"last_scheduled_at": None, "posts": []}
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))


def save_queue(queue: dict) -> None:
    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


def git_commit_push(message: str) -> bool:
    """Commit social_queue.json and push, rebasing on races. Returns True on success
    (or if there was nothing to commit). This is the durability primitive the
    claim/finalize steps rely on."""
    _git("config", "user.name", "github-actions[bot]")
    _git("config", "user.email", "github-actions[bot]@users.noreply.github.com")
    _git("add", "data/social_queue.json")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return True  # nothing to commit
    if _git("commit", "-m", message).returncode != 0:
        return False
    for i in range(5):
        pull = _git("pull", "--rebase", "--autostash")
        if pull.returncode == 0 and _git("push").returncode == 0:
            return True
        print(f"push race, retry {i + 1}...")
        time.sleep(3)
    return False


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


def due_pending(queue: dict, now: datetime) -> list:
    """Entries eligible to post: status 'pending' AND scheduled_at in the past.
    Anything already 'posting'/'posted'/'error' is NEVER selected — the core
    at-most-once invariant."""
    out = []
    for entry in queue.get("posts", []):
        if entry.get("status") != "pending":
            continue
        try:
            scheduled_dt = datetime.fromisoformat(entry.get("scheduled_at", ""))
        except ValueError:
            print(f"Invalid scheduled_at, skipping: {entry.get('title', '')}")
            continue
        if scheduled_dt <= now:
            out.append(entry)
    return out


def main() -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from post_to_linkedin import post_to_linkedin

    queue = load_queue()
    now = datetime.now(timezone.utc)
    posts_made = 0

    # Surface entries a previous run claimed but never finalized (crash / failed
    # finalize). We deliberately do NOT repost them — at-most-once.
    stuck = [e for e in queue.get("posts", []) if e.get("status") == "posting"]
    for e in stuck:
        print(f"WARNING: entry stuck in 'posting' (claimed, not finalized) — NOT reposting: {e.get('title', '')}")

    for entry in due_pending(queue, now):
        title = entry.get("title", "")
        url = entry.get("url", "")
        print(f"Processing: {title} ({url})")

        if not poll_until_live(url):
            print(f"Article not live yet, leaving as pending: {url}")
            continue

        # CLAIM — persist "posting" BEFORE the API call. After this commit lands the
        # entry is unreachable by any future run, so it can never be posted twice.
        entry["status"] = "posting"
        entry["claimed_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        save_queue(queue)
        if not git_commit_push(f"claim: posting '{title[:60]}'"):
            print("ERROR: could not persist claim; aborting run WITHOUT posting (dup-safe).")
            sys.exit(1)

        # POST
        try:
            urn = post_to_linkedin(
                title=title, url=url,
                social_hook=entry.get("social_hook", ""), tags=entry.get("tags", []),
            )
            entry["status"] = "posted"
            if urn:
                entry["post_urn"] = urn
            posts_made += 1
            print(f"Posted to LinkedIn: {title}")
        except SystemExit as exc:
            # post_to_linkedin exits on a non-2xx response or missing env → the post
            # was NOT created, so it's safe to return the entry to 'pending' to retry.
            entry["status"] = "pending"
            entry.pop("claimed_at", None)
            print(f"LinkedIn post failed (not posted, will retry) for '{title}': {exc}")
        except Exception as exc:  # noqa: BLE001
            # Ambiguous (e.g. network timeout mid-request) — the post MAY have landed.
            # Mark 'error' (never auto-retry) to stay dup-safe; surfaced for review.
            entry["status"] = "error"
            entry["error"] = str(exc)[:200]
            print(f"Ambiguous error posting '{title}' — marking 'error', will NOT retry: {exc}")

        # FINALIZE — persist the outcome. If this fails the entry stays 'posting' in
        # the repo, which is still never reposted (dup-proof), just surfaced.
        save_queue(queue)
        if not git_commit_push(f"finalize: {entry['status']} '{title[:60]}'"):
            print("ERROR: could not persist finalize; entry remains 'posting' (won't be reposted).")
            sys.exit(1)

    print(f"Done. Posts made this run: {posts_made}")


def _selftest() -> None:
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    q = {"posts": [
        {"title": "due-pending", "status": "pending", "scheduled_at": "2026-01-01T00:00:00Z"},
        {"title": "future-pending", "status": "pending", "scheduled_at": "2026-02-01T00:00:00Z"},
        {"title": "already-posting", "status": "posting", "scheduled_at": "2026-01-01T00:00:00Z"},
        {"title": "already-posted", "status": "posted", "scheduled_at": "2026-01-01T00:00:00Z"},
        {"title": "errored", "status": "error", "scheduled_at": "2026-01-01T00:00:00Z"},
    ]}
    picked = [e["title"] for e in due_pending(q, now)]
    assert picked == ["due-pending"], picked  # only pending+due; never posting/posted/error
    print("process_linkedin_queue self-check passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
