# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A daily arXiv paper digest that runs as a GitHub Actions cron. A Python agent (`agent/`) picks one paper per day against the user's stated interests and writes a long-form explainer as a Markdown file into the Astro site (`site/`). The static site is auto-deployed by Cloudflare Pages / Vercel on push. A Telegram bot pings the user with the link. The repo is designed as a fork-and-own template.

## Commands

Python agent (run from `agent/`):

```bash
python run_daily.py              # Full pipeline: fetch → rank → explain → write → push to Telegram
python run_daily.py --dry-run    # Pick paper, skip write + Telegram (safe for prompt iteration)
python run_daily.py --date YYYY-MM-DD   # Backfill a specific day
```

Required env vars: `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SITE_URL`. Run from the **repo root** (`python agent/run_daily.py`), not from inside `agent/` — relative paths in `config.yaml` anchor at the repo root, enforced in `config_loader.py`.

Install Python deps: `pip install -r requirements.txt` (requires `requests`, `pdfplumber`, `PyYAML` — no provider SDK, every LLM call goes through OpenRouter via `agent/llm.py`).

Astro site (run from `site/`):

```bash
npm install
npm run dev         # Preview at http://localhost:4321
npm run build       # Outputs to site/dist (what Cloudflare Pages deploys)
npm run preview     # Serve the built dist
```

There is no test suite and no linter wired in — changes are validated by `--dry-run` locally and by the Actions workflow.

## Architecture

The pipeline is a linear 6-step chain. Each step is its own module in `agent/` and is called in order from `run_daily.py::main()`. Read these in order to understand the data flow:

1. `config_loader.load_config()` — merges `config/config.yaml` with env vars. Env vars win. Also loads `config/interests.md` verbatim as a string — this file is the **steering wheel** and is re-read every run.
2. `fetch_arxiv.fetch_recent_papers()` — hits the arXiv Atom API across categories listed in `config.yaml::arxiv_categories`, parses entries, dedupes against `history/history.json` so papers are never re-picked.
3. `rank_papers` — **two-stage ranking**:
   - `prefilter_by_signal()` scores papers deterministically (citations, code availability, category match) and cuts the list to a shortlist. No LLM call.
   - `llm_pick_winner()` then calls the `ranker_model` from `config.yaml` (via `agent/llm.py` → OpenRouter) to pick one winner from the shortlist using `interests.md` as the rubric. This is the only place taste is encoded — edits to `interests.md` change rankings immediately.
4. `generate_explainer.generate_deep_explainer()` — downloads the PDF via `_download_and_extract()` (pdfplumber), sends extracted text + abstract to the `explainer_model` via `agent/llm.py`, returns a ~3,000-word explainer with TL;DR, hook, and body. `max_tokens=16000`.
5. `write_post.write_post()` — writes the explainer to `site/src/content/papers/YYYY-MM-DD-<slug>-<arxiv-id>.md` with YAML frontmatter. The frontmatter schema is enforced by `site/src/content/config.ts` (Zod) — any change to written fields must match that schema or the Astro build fails.
6. `notify_telegram.send_ping()` — HTML-formatted Telegram message linking to `{SITE_URL}/papers/{slug}`.

Model choice is centralized in `config/config.yaml` (`ranker_model`, `explainer_model`, `video_model`) and passed into each call site as an argument. Every model call — regardless of provider — goes through `agent/llm.py::call_llm()` which hits OpenRouter's OpenAI-compatible endpoint. Swapping from Claude Opus to Gemini Pro or GPT-4o is a one-line `config.yaml` edit, zero code change.

## Where behavior lives (non-obvious)

- **Taste / topic selection:** `config/interests.md` (not in code). The agent reads it fresh each run; higher items carry more weight. `config/interests.example.md` is the template — real file is `config/interests.md` and is gitignored.
- **Schema of written posts:** `site/src/content/papers/*.md` frontmatter must satisfy `site/src/content/config.ts`. If you add a field in `write_post.py::_frontmatter()`, add it to the Zod schema too, or the site build breaks.
- **Design tokens:** all colors, fonts, spacing live as CSS variables at the top of `site/src/styles/global.css`. There is no Tailwind.
- **KaTeX + Mermaid:** equations and diagrams in explainers render through `remark-math` / `rehype-katex` and client-side Mermaid. Prompt changes in `generate_explainer.py` that alter equation formatting can silently break rendering — preview locally with `npm run dev`.
- **Seed entry:** `site/src/content/papers/2026-04-18-welcome-0000.00000.md` exists only so the Astro content collection isn't empty on first deploy. Fork consumers delete it after their first real run.

## GitHub Actions flow

`.github/workflows/daily.yml` runs at 01:30 UTC (= 7 AM IST). It: checks out → installs Python deps → runs `python run_daily.py` → `git commit -am` the new paper file and the updated `history/history.json` → `git push`. The push triggers Cloudflare Pages (or Vercel) to rebuild and deploy. The workflow has `concurrency: daily-paper` with `cancel-in-progress: false`, so overlapping runs queue rather than race. The commented-out `deploy-pages` job is the alternative path if the user picks GitHub Pages over Cloudflare/Vercel — it requires a committed `site/package-lock.json`.

## YAML escaping in write_post.py

`write_post._yaml_escape()` handles strings containing YAML-hostile characters (colons, quotes, leading dashes) for the frontmatter. If you change frontmatter serialization, run through `--dry-run` + `npm run build` locally — Astro's content collection will reject malformed YAML with a cryptic error at build time, not agent time.
