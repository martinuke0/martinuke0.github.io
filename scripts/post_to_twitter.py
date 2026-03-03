#!/usr/bin/env python3
"""Post a tweet via X API v2 using OAuth 1.0a (tweepy)."""

import os
import sys
from pathlib import Path

import tweepy

sys.path.insert(0, str(Path(__file__).parent))
from config import TWITTER_TEMPLATE


def build_tweet(title: str, url: str, description: str, tags: list[str]) -> str:
    hashtags = " ".join(f"#{t.replace(' ', '')}" for t in tags[:3])
    # Use first two sentences of description as the hook
    sentences = [s.strip() for s in description.replace("  ", " ").split(". ") if s.strip()]
    hook = ". ".join(sentences[:2])
    if hook and not hook.endswith("."):
        hook += "."

    tweet = TWITTER_TEMPLATE.format(hook=hook, url=url, hashtags=hashtags)

    # Enforce 280-char limit: shorten hook if needed
    if len(tweet) > 280:
        max_hook_len = 280 - len(url) - len(hashtags) - len("\n\nFull guide → \n\n") - 5
        hook = hook[:max_hook_len].rsplit(" ", 1)[0] + "…"
        tweet = TWITTER_TEMPLATE.format(hook=hook, url=url, hashtags=hashtags)

    return tweet[:280]


def post_tweet(title: str, url: str, description: str, tags: list[str]) -> None:
    api_key = os.environ.get("TWITTER_API_KEY")
    api_secret = os.environ.get("TWITTER_API_SECRET")
    access_token = os.environ.get("TWITTER_ACCESS_TOKEN")
    access_token_secret = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")

    missing = [
        name
        for name, val in [
            ("TWITTER_API_KEY", api_key),
            ("TWITTER_API_SECRET", api_secret),
            ("TWITTER_ACCESS_TOKEN", access_token),
            ("TWITTER_ACCESS_TOKEN_SECRET", access_token_secret),
        ]
        if not val
    ]
    if missing:
        sys.exit(f"Error: Missing env vars: {', '.join(missing)}")

    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )

    tweet_text = build_tweet(title, url, description, tags)
    print(f"Posting tweet ({len(tweet_text)} chars):\n{tweet_text}", file=sys.stderr)

    response = client.create_tweet(text=tweet_text)
    tweet_id = response.data["id"]
    print(f"Tweet posted: https://x.com/i/web/status/{tweet_id}")


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Post a tweet about a new blog article.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--tags", default="[]", help="JSON array of tag strings")
    args = parser.parse_args()

    post_tweet(
        title=args.title,
        url=args.url,
        description=args.description,
        tags=json.loads(args.tags),
    )
