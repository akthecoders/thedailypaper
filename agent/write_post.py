"""Write the daily explainer as an Astro content collection entry.

Lands in site/src/content/papers/YYYY-MM-DD-slug.md with YAML frontmatter
that matches the Zod schema in site/src/content/config.ts.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def _slug(text: str, max_len: int = 60) -> str:
    t = re.sub(r"[^\w\s-]", "", text).strip().lower()
    t = re.sub(r"[\s_-]+", "-", t)
    return t[:max_len].rstrip("-")


def _yaml_list(items: list[str], indent: int = 2) -> str:
    pad = " " * indent
    return "\n".join(f"{pad}- {_yaml_escape(x)}" for x in items)


def _clean_str(s: str) -> str:
    """Strip C0/C1 control characters (except tab and newline) that break YAML parsers."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", s)


def _yaml_escape(s: str) -> str:
    """Strip non-printable chars, then quote strings that contain YAML-hostile chars."""
    s = _clean_str(s)
    if any(c in s for c in [":", "#", "'", '"', "\n", "[", "]", "{", "}"]):
        escaped = s.replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _frontmatter(paper: dict, explainer: dict) -> str:
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cat_tag = paper["primary_category"].replace(".", "-")

    tags = list(set(explainer.get("tags", []) + [cat_tag]))
    authors_short = paper["authors"][:10]

    return f"""---
title: {_yaml_escape(paper['title'])}
arxivId: "{paper['arxiv_id']}"
publishedDate: {today_iso}
paperDate: {paper['published'][:10]}
primaryCategory: {paper['primary_category']}
pdfUrl: {paper['pdf_url']}
absUrl: {paper['abs_url']}
pickReason: {_yaml_escape(paper.get('_pick_reason', ''))}
tldr: {_yaml_escape(explainer['tldr'])}
hook: {_yaml_escape(explainer.get('hook', ''))}
authors:
{_yaml_list(authors_short)}
tags:
{_yaml_list(tags)}
---

"""


def write_post(
    paper: dict,
    explainer: dict,
    site_root: Path,
) -> tuple[Path, str]:
    """Write to site/src/content/papers/YYYY-MM-DD-slug.md.
    Returns (file_path, url_slug). The url_slug is what goes in
    https://yoursite.com/papers/{slug}.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title_slug = _slug(paper["title"])
    # Slug convention: date-title-id — sorts chronologically in filesystem,
    # but URL uses just title-id (cleaner)
    filename = f"{today}-{title_slug}-{paper['arxiv_id']}.md"
    # Astro strips dots from content-collection slugs, so the arxiv id
    # `2604.15694` becomes `260415694` in the URL. Mirror that here so the
    # post_url we emit actually resolves.
    url_slug = f"{title_slug}-{paper['arxiv_id'].replace('.', '')}"

    target_dir = site_root / "src" / "content" / "papers"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename

    content = _frontmatter(paper, explainer) + _clean_str(explainer["markdown"])
    target.write_text(content, encoding="utf-8")
    log.info(f"Wrote {len(content)} chars to {target}")
    return target, url_slug
