"""Daily paper explainer — main orchestrator.

Usage:
    python run_daily.py           # Normal run
    python run_daily.py --dry-run # Pick paper but don't write/ping
    python run_daily.py --date 2026-04-17  # Backfill a specific day
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fetch_arxiv import fetch_recent_papers
from rank_papers import prefilter_by_signal, llm_pick_winner
from generate_explainer import generate_deep_explainer
from write_post import write_post
from notify_telegram import send_ping
from send_newsletter import send_newsletter, dry_render as dry_render_newsletter
from config_loader import load_config, REPO_ROOT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def already_picked(arxiv_id: str, history_path: Path) -> bool:
    if not history_path.exists():
        return False
    history = json.loads(history_path.read_text())
    return arxiv_id in {entry["arxiv_id"] for entry in history}


def record_pick(paper: dict, history_path: Path) -> None:
    history = []
    if history_path.exists():
        history = json.loads(history_path.read_text())
        # Safety net: keep the previous version as a rolling backup so a bad
        # write (disk full, interrupted CI, etc.) can be recovered by hand.
        history_path.with_suffix(history_path.suffix + ".prev").write_text(
            json.dumps(history, indent=2)
        )
    history.append({
        "date": datetime.now(timezone.utc).isoformat(),
        "arxiv_id": paper["arxiv_id"],
        "title": paper["title"],
    })
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2))


def merge_backlog(
    today_shortlist: list[dict],
    history_path: Path,
    repo_root: Path,
    days: int = 7,
    keep_top: int = 20,
) -> list[dict]:
    """Pull unpicked candidates from the last `days` of archives, merge with
    today's shortlist, and return the highest-scoring `keep_top` rows.

    Prevents strong papers from being lost when they happened to share a day
    with an even-stronger paper. Costs nothing at the LLM level — the merge
    is a pure score-sort over data we've already archived.
    """
    today_ids = {p["arxiv_id"] for p in today_shortlist}
    picked_ids = set()
    if history_path.exists():
        try:
            picked_ids = {e["arxiv_id"] for e in json.loads(history_path.read_text())}
        except Exception as e:
            log.warning(f"History read failed, skipping backlog merge: {e}")
            return today_shortlist

    archive_dir = repo_root / "history" / "candidates"
    if not archive_dir.exists():
        return today_shortlist

    archives = sorted(archive_dir.glob("*.json"), reverse=True)[:days]
    backlog: list[dict] = []
    for path in archives:
        try:
            rows = json.loads(path.read_text())
        except Exception:
            continue
        for r in rows:
            aid = r.get("arxiv_id")
            if not aid or aid in today_ids or aid in picked_ids:
                continue
            backlog.append(r)
            today_ids.add(aid)  # dedupe across archive files

    if not backlog:
        return today_shortlist

    log.info(f"Backlog merge: {len(backlog)} unpicked candidates from last {days} days")

    # Merge and re-sort. Archive rows use "score" key; fresh shortlist uses "_score".
    combined = []
    for p in today_shortlist:
        combined.append((p.get("_score", 0.0), p))
    for b in backlog:
        # Rehydrate the archive row into the shape prefilter_by_signal produces
        # so downstream code (ranker, explainer) can use it without special cases.
        rehydrated = {
            "arxiv_id": b["arxiv_id"],
            "title": b["title"],
            "authors": b.get("authors", []),
            "primary_category": b.get("primary_category", ""),
            "abstract": b.get("abstract", ""),
            "pdf_url": b.get("pdf_url", ""),
            "abs_url": b.get("abs_url", ""),
            "published": b.get("published", ""),
            "_score": b.get("score", 0.0),
            "_ss": {
                "citationCount": b.get("citation_count"),
                "influentialCitationCount": b.get("influential_citation_count"),
            },
            "_from_backlog": True,
        }
        combined.append((b.get("score", 0.0), rehydrated))

    combined.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in combined[:keep_top]]


def archive_shortlist(shortlist: list[dict], target_date, repo_root: Path) -> None:
    """Persist the day's scored shortlist to history/candidates/YYYY-MM-DD.json.

    This is the foundation for Phase 2 backlog-aware picking: once we have a
    week of archived shortlists, we can compare today's top candidate against
    unpicked candidates from prior days and pick from the backlog when today
    is weak. No LLM cost — just the deterministic scores we already compute.
    """
    archive_dir = repo_root / "history" / "candidates"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{target_date}.json"
    trimmed = []
    for p in shortlist:
        trimmed.append({
            "arxiv_id": p["arxiv_id"],
            "title": p["title"],
            "authors": p.get("authors", [])[:5],
            "primary_category": p.get("primary_category"),
            "abstract": p.get("abstract", "")[:1000],
            "pdf_url": p.get("pdf_url"),
            "abs_url": p.get("abs_url"),
            "published": p.get("published"),
            "score": p.get("_score"),
            "citation_count": (p.get("_ss") or {}).get("citationCount"),
            "influential_citation_count": (p.get("_ss") or {}).get("influentialCitationCount"),
        })
    archive_path.write_text(json.dumps(trimmed, indent=2))
    log.info(f"Archived {len(trimmed)} scored candidates to {archive_path.relative_to(repo_root)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD, backfill")
    parser.add_argument(
        "--dry-newsletter",
        action="store_true",
        help="Render newsletter HTML+text to stdout and exit before commit. Useful for prompt-iterating the email template.",
    )
    parser.add_argument(
        "--skip-newsletter",
        action="store_true",
        help="Run the full pipeline but skip the newsletter send step.",
    )
    args = parser.parse_args()

    cfg = load_config()
    history_path = Path(cfg["history_path"])

    # 1. Fetch — walk back up to LOOKBACK_DAYS until we find papers.
    # arXiv doesn't publish on weekends, so Monday's run (looking at Sunday)
    # and Sunday's run (looking at Saturday) would otherwise exit empty.
    if args.date:
        candidate_dates = [datetime.strptime(args.date, "%Y-%m-%d").date()]
    else:
        today_utc = datetime.now(timezone.utc).date()
        LOOKBACK_DAYS = 4
        candidate_dates = [today_utc - timedelta(days=d) for d in range(1, LOOKBACK_DAYS + 1)]

    log.info(f"Fetching arXiv (will try dates: {[str(d) for d in candidate_dates]})")
    candidates = []
    target_date = candidate_dates[0]
    for d in candidate_dates:
        log.info(f"Trying {d}...")
        batch = fetch_recent_papers(
            categories=cfg["arxiv_categories"],
            target_date=d,
            max_per_category=100,
        )
        batch = [p for p in batch if not already_picked(p["arxiv_id"], history_path)]
        if batch:
            candidates = batch
            target_date = d
            break
        log.info(f"  → no candidates on {d}, trying earlier date")

    log.info(f"{len(candidates)} candidates after dedup (target date: {target_date})")
    if not candidates:
        log.warning(f"No candidates across {len(candidate_dates)} days — exiting")
        return 0

    # 2. Signal pre-filter → top 20
    log.info("Pre-filtering by engagement signal...")
    shortlist = prefilter_by_signal(candidates, top_k=20)
    log.info(f"Shortlist: {len(shortlist)} papers")

    # Phase 1 of the backlog system: archive the scored shortlist before we
    # narrow down to a single winner.
    archive_shortlist(shortlist, target_date, REPO_ROOT)

    # 2b. Backlog-aware augmentation: pull the best unpicked candidates from
    # the last 7 days' archives so today's LLM ranker sees a richer pool.
    # A strong paper that lost to an even-stronger paper on its original day
    # doesn't get silently dropped forever.
    shortlist = merge_backlog(shortlist, history_path, REPO_ROOT, days=7, keep_top=20)
    log.info(f"After backlog merge: {len(shortlist)} papers considered")

    # 3. Ranker model picks winner against interests
    interests = Path(cfg["interests_path"]).read_text()
    ranker_model = cfg["ranker_model"]
    log.info(f"{ranker_model} selecting winner...")
    winner = llm_pick_winner(shortlist, interests=interests, model=ranker_model)
    log.info(f"Winner: {winner['arxiv_id']} — {winner['title']}")

    if args.dry_run:
        log.info("Dry run — stopping before generation")
        print(json.dumps(winner, indent=2))
        return 0

    # 4. Deep explainer
    explainer_model = cfg["explainer_model"]
    log.info(f"Generating deep explainer with {explainer_model} (2-4 min)...")
    explainer = generate_deep_explainer(winner, model=explainer_model, target_minutes=20)

    # 5a. Write to Astro content collection
    site_root = Path(cfg["site_root"])
    post_path, url_slug = write_post(winner, explainer, site_root=site_root)
    log.info(f"Post written: {post_path}")

    # 5b. Newsletter ------------------------------------------------------
    post_url = f"{cfg['site_url'].rstrip('/')}/papers/{url_slug}"
    date_pretty = datetime.utcnow().strftime("%b %d, %Y")

    if args.dry_newsletter:
        dry_render_newsletter(
            winner=winner,
            explainer=explainer,
            post_url=post_url,
            site_url=cfg["site_url"],
            date_pretty=date_pretty,
        )
        log.info("dry-newsletter done — exiting before commit/push")
        return 0

    if cfg["newsletter_enabled"] and not args.skip_newsletter:
        if not cfg["resend_api_key"] or not cfg["resend_audience_id"]:
            log.warning(
                "newsletter_enabled but RESEND_API_KEY/RESEND_AUDIENCE_ID missing — skipping send"
            )
        else:
            try:
                broadcast_id = send_newsletter(
                    winner=winner,
                    explainer=explainer,
                    post_url=post_url,
                    site_url=cfg["site_url"],
                    date_pretty=date_pretty,
                    api_key=cfg["resend_api_key"],
                    audience_id=cfg["resend_audience_id"],
                    from_address=cfg["newsletter_from"],
                    reply_to=cfg["newsletter_reply_to"],
                )
                log.info("newsletter sent, broadcast_id=%s", broadcast_id)
            except Exception as e:
                log.error("newsletter send failed (continuing): %s", e)
    else:
        log.info(
            "newsletter skipped (enabled=%s, skip=%s)",
            cfg["newsletter_enabled"],
            args.skip_newsletter,
        )

    # 5c. Telegram ping with site URL
    send_ping(
        winner=winner,
        explainer_tldr=explainer["tldr"],
        post_url=post_url,
        bot_token=cfg["telegram_bot_token"],
        chat_id=cfg["telegram_chat_id"],
    )
    log.info("Telegram sent")

    # 6. Record
    record_pick(winner, history_path)
    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
