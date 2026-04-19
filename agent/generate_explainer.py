"""Generate reimplementation-grade explainer from a paper PDF."""
from __future__ import annotations

import io
import json
import logging

import pdfplumber
import requests

from llm import call_llm

log = logging.getLogger(__name__)


def _download_and_extract(pdf_url: str) -> tuple[str, list[bytes]]:
    log.info(f"Downloading PDF: {pdf_url}")
    resp = requests.get(pdf_url, timeout=60, headers={"User-Agent": "daily-papers/1.0"})
    resp.raise_for_status()
    pdf_bytes = resp.content

    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_parts.append(t)

    full_text = "\n\n".join(text_parts)
    log.info(f"Extracted {len(full_text)} chars across {len(text_parts)} pages")
    return full_text, []


EXPLAINER_PROMPT = """You are writing a reimplementation-grade research deep-dive that will be published on a public technical blog. Target reader: strong ML/engineering background. Target length: a thorough 20-minute read that gives someone enough detail to build a working prototype of the core method.

Tone: editorial but precise. Third-person, not first-person. No filler. No cheerleading. No "fascinating" or "groundbreaking." State what the paper does and evaluate it honestly.

# Paper metadata
Title: {title}
Authors: {authors}
Category: {category}
arXiv: {arxiv_id}
Published: {published}

# Why this paper was selected
{pick_reason}

# Full paper text
{paper_text}

---

Write the explainer. Follow this structure EXACTLY. Use markdown.

## TL;DR
3-4 sentences. Problem, core idea, main result.

## Why this matters
2-3 paragraphs. What's broken about the status quo. How this contributes. Be honest about scope — don't overhype.

## Background
Prerequisites with intuition (not just definitions). Name 2-3 prior works this builds on with a one-line summary each.

## The core idea
Big idea in plain language BEFORE math. Use an analogy if it helps. After this section, a reader should be able to explain the paper in one minute.

## The method
Technical deep-dive. Include:
- Formal problem setup with notation defined
- Algorithm as pseudocode or loss function with every term explained
- Key equations in LaTeX ($...$ inline or $$...$$ display). Render correctly — this will appear on a site with KaTeX.
- Architectural choices and WHY
- Critical hyperparameters and their values

This section is the bulk. Be thorough and precise.

## Architecture

Include ONE Mermaid diagram of the method's flow. Use a ```mermaid fenced block. Under 15 nodes. Label nodes clearly.

## Results

- Main quantitative results described in words (don't reproduce tables verbatim — summarize)
- Which experiments are most convincing and why
- Which ablations teach you something interesting

## Limitations

What this method doesn't do. Where it would break. What's missing from the evaluation. Be the skeptical reviewer.

## Reimplementation notes

- Implementation gotchas
- Compute requirement (rough GPU-hours or dollar cost)
- Dataset and codebase links if mentioned
- Effort estimate for a solo engineer to get a working prototype

## Production implementation

How a competent team would ship this as a real product feature, not a notebook demo. Be concrete — name specific tools, not categories.

- **Tech stack**: languages, frameworks, model-serving runtime (vLLM, TensorRT-LLM, Triton, SGLang, etc.), vector store / database / cache choices. Pick the shortest path that actually works at target scale.
- **Data pipeline**: where training / reference data comes from, how it's versioned and refreshed, what the inference-time data flow looks like end-to-end (ingress → preprocessing → model → post-processing → response).
- **Deployment shape**: batch job, online service, edge, or embedded. Expected latency budget and throughput target. Hardware SKU (e.g. "1× A100 80GB handles ~X QPS at batch 8").
- **Failure modes in production** that don't show up in the paper: distribution shift, adversarial input, cold start, long tail, degraded upstream, cost blow-up. For each, how the system detects and degrades gracefully.
- **Evaluation plan**: offline metrics to track in CI, online metrics (A/B test design, guardrails, business KPIs), and the one failure the team must never ship.
- **Rollout strategy**: shadow mode → % traffic ramp → full → what would trigger rollback. Name the single most dangerous failure mode and how it's monitored.
- **Cost back-of-envelope**: rough $/1K requests or $/user/month at realistic scale. Where the cost ceiling sits and the first lever to pull when it's breached.

Skip sections that genuinely don't apply (e.g. a pure theory paper may have no deployment shape), but don't skip them just because the paper doesn't mention them — infer from the method.

## Related reading

3-5 papers genuinely relevant to understanding this one. One line each on why.

## Key equations

The 2-4 equations most worth remembering. One-line description each.

---

After the markdown, append a JSON block for the site + Telegram ping:

```json
{{
  "tldr": "<one sentence TL;DR for the phone notification>",
  "hook": "<why read it today, one line>",
  "tags": ["<3-6 topical tags, lowercase hyphenated, like 'transformers', 'market-microstructure'>"]
}}
```

Constraints:
- Never quote more than ~15 words consecutively from the source paper. Paraphrase everything.
- Don't reproduce figures/tables — summarize them.
- Equations are fair to render (they're facts, not expression).
- Reimplementation-grade means a strong engineer could build a prototype from this alone."""


def generate_deep_explainer(winner: dict, model: str, target_minutes: int = 20) -> dict:
    full_text, _ = _download_and_extract(winner["pdf_url"])

    MAX_PAPER_CHARS = 150_000
    if len(full_text) > MAX_PAPER_CHARS:
        log.warning(f"Paper is {len(full_text)} chars, truncating to {MAX_PAPER_CHARS}")
        full_text = full_text[:MAX_PAPER_CHARS] + "\n\n[... paper truncated ...]"

    prompt = EXPLAINER_PROMPT.format(
        title=winner["title"],
        authors=", ".join(winner["authors"]),
        category=winner["primary_category"],
        arxiv_id=winner["arxiv_id"],
        published=winner["published"][:10],
        pick_reason=winner.get("_pick_reason", ""),
        paper_text=full_text,
    )

    log.info(f"Calling {model} for explainer generation...")
    output = call_llm(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=16000,
    )

    markdown_body = output
    tldr = winner["title"]
    hook = ""
    tags = []
    if "```json" in output:
        body, _, rest = output.rpartition("```json")
        markdown_body = body.rstrip()
        json_text = rest.split("```")[0].strip()
        try:
            ping = json.loads(json_text)
            tldr = ping.get("tldr", tldr)
            hook = ping.get("hook", "")
            tags = ping.get("tags", [])
        except json.JSONDecodeError:
            log.warning("Couldn't parse ping JSON — using fallback")

    return {
        "markdown": markdown_body,
        "tldr": tldr,
        "hook": hook,
        "tags": tags,
    }
