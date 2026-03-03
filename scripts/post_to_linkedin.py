#!/usr/bin/env python3
"""Post to LinkedIn via API v2 using an OAuth 2.0 bearer token."""

import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import LINKEDIN_TEMPLATE


def build_post(title: str, url: str, social_hook: str) -> str:
    return LINKEDIN_TEMPLATE.format(title=title, social_hook=social_hook, url=url)


def post_to_linkedin(title: str, url: str, social_hook: str) -> None:
    access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    person_urn = os.environ.get("LINKEDIN_PERSON_URN")

    missing = [
        name
        for name, val in [
            ("LINKEDIN_ACCESS_TOKEN", access_token),
            ("LINKEDIN_PERSON_URN", person_urn),
        ]
        if not val
    ]
    if missing:
        sys.exit(f"Error: Missing env vars: {', '.join(missing)}")

    post_text = build_post(title, url, social_hook)
    print(f"Posting to LinkedIn:\n{post_text}", file=sys.stderr)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": post_text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }

    resp = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers=headers,
        json=payload,
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        sys.exit(f"LinkedIn API error {resp.status_code}: {resp.text}")

    post_id = resp.headers.get("x-restli-id", resp.json().get("id", "unknown"))
    print(f"LinkedIn post created: {post_id}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Post a LinkedIn update about a new blog article.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--social-hook", required=True, dest="social_hook")
    args = parser.parse_args()

    post_to_linkedin(title=args.title, url=args.url, social_hook=args.social_hook)
