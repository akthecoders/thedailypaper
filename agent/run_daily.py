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
from config_loader import load_config

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
    history.append({
        "date": datetime.now(timezone.utc).isoformat(),
        "arxiv_id": paper["arxiv_id"],
        "title": paper["title"],
    })
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD, backfill")
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

    # 5b. Telegram ping with site URL
    post_url = f"{cfg['site_url'].rstrip('/')}/papers/{url_slug}"
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
