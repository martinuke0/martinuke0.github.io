#!/usr/bin/env python3
"""Generate a blog article via OpenRouter and write it to content/posts/."""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI
from slugify import slugify

# Allow running from repo root or scripts/ dir
sys.path.insert(0, str(Path(__file__).parent))
from config import (
    BLOG_BASE_URL,
    CONTENT_DIR,
    DEFAULT_MODEL,
    OPENROUTER_BASE_URL,
    SYSTEM_PROMPT,
)


def build_user_prompt(topic: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"Write a Zero-to-Hero tutorial article about: {topic}\n\n"
        f"Use today's date for the frontmatter: {now}\n"
        "Make the article practical, code-heavy, and suitable for intermediate developers.\n"
        "At the very end of the article (after the Top 10 Resources section), output a JSON block "
        "enclosed in <METADATA>...</METADATA> tags with this exact structure:\n"
        "{\n"
        '  "title": "<article title>",\n'
        '  "slug": "<url-friendly slug>",\n'
        '  "description": "<two-sentence description>",\n'
        '  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],\n'
        '  "social_hook": "<2-3 paragraph LinkedIn-style summary of the article>"\n'
        "}"
    )


def extract_metadata(content: str) -> tuple[str, dict]:
    """Split raw LLM output into (article_markdown, metadata_dict)."""
    match = re.search(r"<METADATA>(.*?)</METADATA>", content, re.DOTALL)
    if not match:
        # Fallback: return content as-is with empty metadata
        return content.strip(), {}

    article = content[: match.start()].strip()
    try:
        metadata = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        metadata = {}

    return article, metadata


def derive_filename(metadata: dict, article: str, date_str: str) -> str:
    """Build YYYY-MM-DD-slug.md filename from metadata or frontmatter."""
    title = metadata.get("title", "")
    if not title:
        # Try to grab title from frontmatter
        fm_match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', article, re.MULTILINE)
        title = fm_match.group(1) if fm_match else "untitled"

    date_prefix = date_str[:10]  # YYYY-MM-DD
    slug = metadata.get("slug") or slugify(title)
    return f"{date_prefix}-{slug}.md"


def generate_article(topic: str) -> dict:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("Error: OPENROUTER_API_KEY environment variable not set.")

    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)

    client = OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
    )

    print(f"Generating article for topic: {topic}", file=sys.stderr)
    print(f"Model: {model}", file=sys.stderr)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(topic)},
        ],
        max_tokens=16000,
    )

    raw = response.choices[0].message.content
    article, metadata = extract_metadata(raw)

    # Determine date from frontmatter for filename
    date_match = re.search(r'^date:\s*["\']?(\S+)["\']?', article, re.MULTILINE)
    date_str = date_match.group(1) if date_match else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    filename = derive_filename(metadata, article, date_str)
    output_path = Path(CONTENT_DIR) / filename

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(article, encoding="utf-8")
    print(f"Article written to: {output_path}", file=sys.stderr)

    slug = metadata.get("slug") or filename.replace(".md", "").split("-", 3)[-1]
    url = f"{BLOG_BASE_URL}posts/{output_path.stem}/"

    social_hook = metadata.get("social_hook", "")
    if not social_hook:
        # Fallback: first 3 substantial paragraphs from the article body
        body = re.sub(r"^---.*?---\s*", "", article, count=1, flags=re.DOTALL)
        paragraphs = []
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("```") or line.startswith("|"):
                continue
            line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
            line = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", line)
            if len(line) > 80:
                paragraphs.append(line)
            if len(paragraphs) == 3:
                break
        social_hook = "\n\n".join(paragraphs)

    result = {
        "title": metadata.get("title", topic),
        "slug": slug,
        "url": url,
        "description": metadata.get("description", ""),
        "tags": metadata.get("tags", []),
        "social_hook": social_hook,
        "file": str(output_path),
    }

    # Write metadata file for downstream queue script (same workflow run)
    meta_path = Path(__file__).parent.parent / "data" / ".last_article_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Article metadata written to: {meta_path}", file=sys.stderr)

    # Print JSON metadata to stdout for downstream workflow steps
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a blog article via OpenRouter.")
    parser.add_argument("--topic", required=True, help="Article topic/prompt")
    args = parser.parse_args()
    generate_article(args.topic)
