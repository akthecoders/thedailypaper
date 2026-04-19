"""Two-stage ranking: signal prefilter then an LLM picks the winner."""
from __future__ import annotations

import json
import logging
import time

import requests

from llm import call_llm

log = logging.getLogger(__name__)

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper"


def _ss_lookup(arxiv_id: str) -> dict | None:
    try:
        resp = requests.get(
            f"{SEMANTIC_SCHOLAR_API}/ARXIV:{arxiv_id}",
            params={"fields": "citationCount,influentialCitationCount,references.externalIds"},
            timeout=10,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.debug(f"SS lookup failed for {arxiv_id}: {e}")
        return None


def _score_paper(paper: dict) -> float:
    score = 0.0
    ss = paper.get("_ss", {})
    citations = ss.get("citationCount", 0) or 0
    influential = ss.get("influentialCitationCount", 0) or 0
    score += min(citations, 50) * 0.5
    score += influential * 3.0

    abstract_lower = paper["abstract"].lower()
    if any(k in abstract_lower for k in ["github.com/", "code available", "open-source", "we release"]):
        score += 10.0
    if any(k in abstract_lower for k in ["state-of-the-art", "sota", "outperform", "surpass"]):
        score += 3.0
    if len(paper["title"]) > 180:
        score -= 5.0

    cat_weights = {
        "cs.LG": 1.0, "cs.AI": 1.0, "cs.CL": 0.9,
        "q-fin.TR": 1.2, "q-fin.CP": 1.1,
        "cs.DS": 0.8, "stat.ML": 0.9,
    }
    score *= cat_weights.get(paper["primary_category"], 0.7)
    return score


def prefilter_by_signal(candidates: list[dict], top_k: int = 20) -> list[dict]:
    log.info(f"Enriching {len(candidates)} candidates with Semantic Scholar...")
    for i, p in enumerate(candidates):
        if i > 0 and i % 10 == 0:
            log.info(f"  enriched {i}/{len(candidates)}")
        p["_ss"] = _ss_lookup(p["arxiv_id"]) or {}
        time.sleep(1.05)
        p["_score"] = _score_paper(p)

    ranked = sorted(candidates, key=lambda p: p["_score"], reverse=True)
    return ranked[:top_k]


def llm_pick_winner(shortlist: list[dict], interests: str, model: str) -> dict:
    catalog_lines = []
    for i, p in enumerate(shortlist):
        catalog_lines.append(
            f"[{i}] {p['title']}\n"
            f"    Category: {p['primary_category']} | Score: {p['_score']:.1f}\n"
            f"    Authors: {', '.join(p['authors'][:3])}{'...' if len(p['authors']) > 3 else ''}\n"
            f"    Abstract: {p['abstract'][:600]}..."
        )
    catalog = "\n\n".join(catalog_lines)

    prompt = f"""You are curating a daily research digest. Pick THE SINGLE BEST paper from the shortlist below against the user's stated interests.

Selection criteria (in order):
1. Alignment with interests file (most important)
2. Novelty of method (not incremental)
3. Reimplementation potential (has clear algorithm, ideally code)
4. Teaching value (result is surprising or clarifies a technique)

Avoid: pure surveys, benchmark-only papers, papers already well-known.

=== USER INTERESTS ===
{interests}

=== SHORTLIST ===
{catalog}

Respond with ONLY a JSON object, no prose:
{{"pick_index": <int>, "reason": "<one sentence why this paper, referencing the interests>"}}"""

    text = call_llm(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
    ).strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    decision = json.loads(text.strip())

    winner = shortlist[decision["pick_index"]]
    winner["_pick_reason"] = decision["reason"]
    return winner
