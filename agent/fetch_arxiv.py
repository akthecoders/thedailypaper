"""Fetch recent arXiv papers across multiple categories."""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

log = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}


def _parse_entry(entry: ET.Element) -> dict[str, Any]:
    def find_text(tag: str) -> str:
        el = entry.find(f"atom:{tag}", NS)
        return (el.text or "").strip() if el is not None else ""

    arxiv_id = find_text("id").rsplit("/", 1)[-1]
    arxiv_id_base = arxiv_id.rsplit("v", 1)[0] if "v" in arxiv_id else arxiv_id

    authors = [
        (a.find("atom:name", NS).text or "").strip()
        for a in entry.findall("atom:author", NS)
    ]
    categories = [c.attrib.get("term", "") for c in entry.findall("atom:category", NS)]

    pdf_url = ""
    for link in entry.findall("atom:link", NS):
        if link.attrib.get("title") == "pdf":
            pdf_url = link.attrib.get("href", "")
            break

    return {
        "arxiv_id": arxiv_id_base,
        "arxiv_id_versioned": arxiv_id,
        "title": find_text("title").replace("\n", " ").strip(),
        "abstract": find_text("summary").replace("\n", " ").strip(),
        "authors": authors,
        "categories": categories,
        "primary_category": categories[0] if categories else "",
        "published": find_text("published"),
        "updated": find_text("updated"),
        "pdf_url": pdf_url,
        "abs_url": f"https://arxiv.org/abs/{arxiv_id_base}",
    }


def _fetch_category(category: str, target_date: date, max_results: int = 100) -> list[dict]:
    params = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
        "start": 0,
    }
    log.info(f"Fetching {category} (max {max_results})")
    resp = requests.get(ARXIV_API, params=params, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    entries = root.findall("atom:entry", NS)
    papers = [_parse_entry(e) for e in entries]

    start_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)

    filtered = []
    for p in papers:
        try:
            pub = datetime.fromisoformat(p["published"].replace("Z", "+00:00"))
            if start_dt <= pub < end_dt:
                filtered.append(p)
        except ValueError:
            continue

    log.info(f"  → {len(filtered)} papers on {target_date}")
    return filtered


def fetch_recent_papers(
    categories: list[str],
    target_date: date,
    max_per_category: int = 100,
) -> list[dict]:
    all_papers: dict[str, dict] = {}
    for i, cat in enumerate(categories):
        if i > 0:
            time.sleep(3.1)  # arXiv rate limit
        try:
            for p in _fetch_category(cat, target_date, max_per_category):
                if p["arxiv_id"] in all_papers:
                    existing = all_papers[p["arxiv_id"]]
                    existing["categories"] = list(set(existing["categories"] + p["categories"]))
                else:
                    all_papers[p["arxiv_id"]] = p
        except Exception as e:
            log.error(f"Failed to fetch {cat}: {e}")
            continue

    result = list(all_papers.values())
    log.info(f"Total unique papers: {len(result)}")
    return result
