"""Send the daily newsletter email via Resend Broadcasts.

Called from run_daily.py after write_post succeeds. Failures are logged but do
not fail the pipeline (Telegram + commit/push must still run).
"""
from __future__ import annotations

import html
import logging
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

RESEND_API_BASE = "https://api.resend.com"

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_templates() -> tuple[str, str]:
    html_tpl = (_TEMPLATES_DIR / "newsletter.html").read_text(encoding="utf-8")
    text_tpl = (_TEMPLATES_DIR / "newsletter.txt").read_text(encoding="utf-8")
    return html_tpl, text_tpl


def _hook_from_explainer(body: str, max_chars: int = 600) -> str:
    """First non-empty paragraph of the body, truncated to max_chars."""
    for para in body.split("\n\n"):
        s = para.strip()
        if not s or s.startswith("#") or s.startswith(">"):
            continue
        if len(s) > max_chars:
            s = s[:max_chars].rsplit(" ", 1)[0] + "…"
        return s
    return ""


def _format_authors(authors: list[str]) -> str:
    if not authors:
        return "Anonymous"
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return " & ".join(authors)
    return f"{authors[0]}, {authors[1]} et al."


def _brace_escape(s: str) -> str:
    """Escape literal `{` and `}` in content so str.format() treats them as text.

    ML paper titles and bodies routinely contain set/interval notation like
    `{k}` or `{n, m}`. Without this, .format() raises KeyError/ValueError.
    """
    return s.replace("{", "{{").replace("}", "}}")


def render_newsletter(
    winner: dict,
    explainer: dict,
    post_url: str,
    site_url: str,
    date_pretty: str,
) -> tuple[str, str]:
    """Return (html_body, text_body)."""
    html_tpl, text_tpl = _load_templates()
    authors = _format_authors(winner.get("authors", []))
    hook = _hook_from_explainer(explainer.get("body", ""))
    host = urlparse(site_url).hostname or site_url
    archive_url = f"{site_url.rstrip('/')}/archive/"

    html_body = html_tpl.format(
        title_escaped=_brace_escape(html.escape(winner["title"])),
        authors_escaped=_brace_escape(html.escape(authors)),
        primary_category=_brace_escape(html.escape(winner.get("primary_category", ""))),
        tldr_escaped=_brace_escape(html.escape(explainer.get("tldr", ""))),
        hook_escaped=_brace_escape(html.escape(hook).replace("\n", "<br>")),
        post_url=post_url,
        archive_url=archive_url,
        site_url=site_url,
        site_host=host,
        date_pretty=date_pretty,
    )
    text_body = text_tpl.format(
        title=_brace_escape(winner["title"]),
        authors=_brace_escape(authors),
        primary_category=_brace_escape(winner.get("primary_category", "")),
        tldr=_brace_escape(explainer.get("tldr", "")),
        hook=_brace_escape(hook),
        post_url=post_url,
        archive_url=archive_url,
        date_pretty=date_pretty,
    )
    return html_body, text_body


def send_newsletter(
    winner: dict,
    explainer: dict,
    post_url: str,
    site_url: str,
    date_pretty: str,
    api_key: str,
    audience_id: str,
    from_address: str,
    reply_to: str,
) -> str:
    """Create + send a Resend Broadcast. Returns the broadcast_id.

    Raises on API errors. Caller is responsible for try/except + logging.
    """
    html_body, text_body = render_newsletter(
        winner, explainer, post_url, site_url, date_pretty,
    )

    # Step 1: create the broadcast.
    create_resp = requests.post(
        f"{RESEND_API_BASE}/broadcasts",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "audience_id": audience_id,
            "from": from_address,
            "subject": winner["title"],
            "html": html_body,
            "text": text_body,
            "reply_to": reply_to,
        },
        timeout=30,
    )
    if not create_resp.ok:
        raise RuntimeError(
            f"Resend broadcasts.create failed: {create_resp.status_code} {create_resp.text[:300]}"
        )
    try:
        broadcast_id = create_resp.json()["id"]
    except (KeyError, ValueError) as exc:
        raise RuntimeError(
            f"Resend broadcasts.create: unexpected response body: {create_resp.text[:300]}"
        ) from exc

    # Step 2: send it.
    send_resp = requests.post(
        f"{RESEND_API_BASE}/broadcasts/{broadcast_id}/send",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    if not send_resp.ok:
        raise RuntimeError(
            f"Resend broadcasts.send failed: {send_resp.status_code} {send_resp.text[:300]}"
        )
    log.info("Resend broadcast queued: %s", broadcast_id)
    return broadcast_id


def dry_render(
    winner: dict,
    explainer: dict,
    post_url: str,
    site_url: str,
    date_pretty: str,
) -> None:
    """Print rendered HTML + text to stdout. Used by --dry-newsletter."""
    html_body, text_body = render_newsletter(
        winner, explainer, post_url, site_url, date_pretty,
    )
    print("========== HTML ==========")
    print(html_body)
    print("========== TEXT ==========")
    print(text_body)
