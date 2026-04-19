"""Send a morning Telegram ping with the TL;DR + link to the published post."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def send_ping(
    winner: dict,
    explainer_tldr: str,
    post_url: str,
    bot_token: str,
    chat_id: str,
) -> None:
    authors_str = ", ".join(winner["authors"][:2])
    if len(winner["authors"]) > 2:
        authors_str += " et al."

    msg = (
        f"📄 <b>Today's paper</b>\n\n"
        f"<b>{_html_escape(winner['title'])}</b>\n"
        f"<i>{_html_escape(authors_str)}</i>\n"
        f"<code>{winner['primary_category']}</code>\n\n"
        f"<b>TL;DR:</b> {_html_escape(explainer_tldr)}\n\n"
        f"📖 <a href=\"{post_url}\">Read the full explainer</a>\n"
        f"🔗 <a href=\"{winner['abs_url']}\">arXiv</a>"
        f" · <a href=\"{winner['pdf_url']}\">PDF</a>"
    )

    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,  # Show a card preview of the blog post
        },
        timeout=15,
    )
    if not resp.ok:
        log.error(f"Telegram send failed: {resp.status_code} {resp.text}")
        resp.raise_for_status()
