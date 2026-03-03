#!/usr/bin/env python3
"""Extract metadata from a generated article .md file and write .last_article_meta.json.

Usage:
    python scripts/extract_article_meta.py path/to/article.md
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import BLOG_BASE_URL

REPO_ROOT = Path(__file__).parent.parent
META_FILE = REPO_ROOT / "data" / ".last_article_meta.json"


def extract(md_path: Path) -> dict:
    content = md_path.read_text(encoding="utf-8")

    # Extract <METADATA> block if present
    meta_match = re.search(r"<METADATA>(.*?)</METADATA>", content, re.DOTALL)
    metadata = {}
    if meta_match:
        try:
            metadata = json.loads(meta_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Fall back to frontmatter for title/description/tags
    title = metadata.get("title") or ""
    if not title:
        m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
        title = m.group(1) if m else md_path.stem

    description = metadata.get("description") or ""
    if not description:
        m = re.search(r'^description:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
        description = m.group(1) if m else ""

    tags = metadata.get("tags") or []
    if not tags:
        m = re.search(r'^tags:\s*(\[.+?\])', content, re.MULTILINE)
        if m:
            try:
                tags = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

    url = f"{BLOG_BASE_URL}posts/{md_path.stem}/"

    social_hook = metadata.get("social_hook") or ""
    if not social_hook:
        social_hook = _extract_intro(content)

    return {
        "title": title,
        "slug": metadata.get("slug") or md_path.stem,
        "url": url,
        "description": description,
        "tags": tags,
        "social_hook": social_hook,
        "file": str(md_path),
    }


def _extract_intro(content: str) -> str:
    """Pull the first 3 non-heading, non-empty paragraphs after the frontmatter."""
    # Strip frontmatter
    body = re.sub(r"^---.*?---\s*", "", content, count=1, flags=re.DOTALL)
    # Strip METADATA block
    body = re.sub(r"<METADATA>.*?</METADATA>", "", body, flags=re.DOTALL)

    paragraphs = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("```") or line.startswith("|"):
            continue
        # Clean markdown links and bold
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", line)
        if len(line) > 80:
            paragraphs.append(line)
        if len(paragraphs) == 3:
            break

    return "\n\n".join(paragraphs)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: extract_article_meta.py <path-to-article.md>")

    md_path = Path(sys.argv[1])
    if not md_path.exists():
        sys.exit(f"Error: file not found: {md_path}")

    result = extract(md_path)
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Metadata written to {META_FILE}")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
