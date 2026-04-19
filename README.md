# The Daily Paper

> One technical paper, explained properly, every morning.

A self-hosted daily technical research digest:

- **Pipeline** — A Python agent that fetches new arXiv papers, picks the single best one against your interests, and generates a reimplementation-grade 3,000-word explainer.
- **Site** — An Astro static site that renders each explainer with proper typography, LaTeX equations (via KaTeX), and Mermaid diagrams.
- **Notifier** — A Telegram bot pings you each morning with the TL;DR and a link.
- **Automation** — GitHub Actions runs the whole thing on a cron schedule. Free to host.

## Architecture

```
 7am IST ─▶ GitHub Actions cron
              │
              ├─▶ Python agent
              │     ├─▶ Fetch arXiv (7 categories, last 24h)
              │     ├─▶ Prefilter by signal (citations, code, etc.)
              │     ├─▶ Claude picks the single best paper
              │     ├─▶ Download PDF, extract text
              │     ├─▶ Claude generates deep explainer
              │     ├─▶ Writes .md to site/src/content/papers/
              │     └─▶ Telegram ping with link to new post
              │
              ├─▶ Git commit + push
              │
              └─▶ Cloudflare Pages (or Vercel) auto-deploys
                   https://yoursite.com/papers/{slug}
```

## Quickstart

### Prerequisites

- GitHub account
- Anthropic API key (from console.anthropic.com)
- Telegram account
- A domain you control (optional — GitHub Pages gives you a free subdomain)

### 1. Fork & clone

```bash
# Click "Fork" on this repo's GitHub page, then:
git clone git@github.com:<your-username>/daily-papers-blog.git
cd daily-papers-blog
```

### 2. Configure

```bash
cp config/config.example.yaml config/config.yaml
cp config/interests.example.md config/interests.md
# Edit config/interests.md to match your research interests
# Edit config/config.yaml and set site_url to your eventual deployed URL
```

Your interests file is the **steering wheel**. The agent reads it fresh every run — edit it anytime your focus shifts. Higher items = higher weight.

### 3. Create the Telegram bot (5 min)

1. Open Telegram, search `@BotFather`
2. Send `/newbot`, follow prompts, save the bot token
3. Send any message to your new bot
4. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` — find your `chat.id` in the JSON response

### 4. Set up GitHub secrets

In your forked repo: **Settings → Secrets and variables → Actions → New repository secret**

Add these four:

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` from console.anthropic.com |
| `TELEGRAM_BOT_TOKEN` | From BotFather above |
| `TELEGRAM_CHAT_ID` | From getUpdates above |
| `SITE_URL` | `https://yoursite.pages.dev` (set after step 5) |

### 5. Deploy the site

Three options. Cloudflare Pages is the smoothest for this setup.

**Option A — Cloudflare Pages (recommended, free)**

1. Sign in at https://dash.cloudflare.com
2. Workers & Pages → Create → Pages → Connect to Git
3. Select your forked repo
4. Build settings:
   - Framework preset: **Astro**
   - Build command: `cd site && npm install && npm run build`
   - Build output directory: `site/dist`
   - Root directory: (leave empty)
5. Environment variables (in Cloudflare Pages settings):
   - `SITE_URL` = the URL Cloudflare gives you (e.g., `https://daily-papers-blog.pages.dev`)
6. Deploy. Copy the final URL and paste it back as `SITE_URL` in GitHub Secrets.

**Option B — Vercel (similar to Cloudflare, also free)**

Same pattern — import repo, framework preset Astro, root `site/`, deploy.

**Option C — GitHub Pages (uncomment the deploy-pages job in .github/workflows/daily.yml)**

Requires a `package-lock.json` (run `cd site && npm install` locally and commit the lockfile first).

### 6. First manual run

In your fork: **Actions tab → Daily Paper workflow → Run workflow**

This triggers the pipeline manually. First successful run should:

1. Pick a paper from yesterday's arXiv (you'll see logs in the Action run)
2. Generate the explainer
3. Commit a new `.md` file to `site/src/content/papers/`
4. Push — which triggers your Cloudflare/Vercel deployment
5. Ping your Telegram

If anything fails, check the Action logs — the first run is the one most likely to need tweaking.

### 7. Delete the seed entry

After your first real paper lands, delete the placeholder:

```bash
git pull
rm site/src/content/papers/2026-04-18-welcome-0000.00000.md
git commit -am "remove seed entry"
git push
```

### 8. Done

The workflow is scheduled for 01:30 UTC daily = **7:00 AM IST**. Edit the cron in `.github/workflows/daily.yml` if you want a different time (use [crontab.guru](https://crontab.guru) to verify).

## Local development

To run the pipeline locally (e.g., to test a prompt change):

```bash
# Python side
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...

cd agent
python run_daily.py --dry-run    # Picks paper but doesn't write/ping
python run_daily.py              # Real run

# Site side (preview with the paper you just generated)
cd ../site
npm install
npm run dev
# Open http://localhost:4321
```

## Tuning

**Getting irrelevant papers?** Edit `config/interests.md`. Add specific topics to "High priority" or "Avoid." The agent reads this file every run.

**Explainers too shallow?** Bump `max_tokens` in `agent/generate_explainer.py` (currently 16000).

**Want different arXiv categories?** Edit `arxiv_categories` in `config/config.yaml`. Common additions: `cs.CV` (computer vision), `cs.DC` (distributed computing), `cs.IR` (info retrieval).

**Want to change the aesthetic?** All design tokens are in `site/src/styles/global.css`. Fonts, colors, spacing — all CSS variables at the top.

## Costs

- **Hosting** (Cloudflare Pages/Vercel): $0
- **GitHub Actions**: $0 (2000 free minutes/month; this uses ~3 min/day)
- **Anthropic API**: ~$1.60/day = ~$48/month using Claude Opus 4.7 for both ranking and generation
- **To reduce API cost to ~$25/month**: swap ranking in `rank_papers.py` to Sonnet 4.6 (cheaper, still great for this task). Keep Opus for the full explainer.

## Structure

```
daily-papers-blog/
├── .github/workflows/
│   └── daily.yml              # Cron + commit + push
├── agent/                     # Python pipeline
│   ├── run_daily.py           # Entry point
│   ├── fetch_arxiv.py
│   ├── rank_papers.py
│   ├── generate_explainer.py
│   ├── write_post.py          # → site/src/content/papers/
│   ├── notify_telegram.py
│   └── config_loader.py
├── config/
│   ├── config.example.yaml
│   └── interests.example.md
├── history/                   # Tracks picked papers (auto-created)
├── site/                      # Astro static site
│   ├── src/
│   │   ├── content/
│   │   │   ├── config.ts      # Zod schema for frontmatter
│   │   │   └── papers/        # Markdown lands here
│   │   ├── layouts/
│   │   ├── components/
│   │   ├── pages/
│   │   └── styles/
│   ├── astro.config.mjs
│   └── package.json
├── requirements.txt
└── README.md
```

## Contributing

This is designed as a template — fork it, make it yours. If you build interesting variations (different aesthetic, different source beyond arXiv, video generation, etc.), open a PR or an issue with a link.

## License

MIT.
