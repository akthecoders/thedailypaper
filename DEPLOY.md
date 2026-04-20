# Deploy

Two deploy surfaces, intentionally separated:

| Component | Runs on | Rebuilds on |
|---|---|---|
| **Astro site** (`site/`) | Dokploy (this guide) | Every `git push` to `main` |
| **Python agent** (`agent/`) | GitHub Actions cron | Daily at 01:30 UTC |

The agent commits new `.md` files into `site/src/content/papers/` and pushes. Dokploy's GitHub webhook fires and rebuilds. That's the whole loop.

---

## 1. GitHub Actions — what the agent needs

Set these in **GitHub → repo Settings → Secrets and variables → Actions → New repository secret**:

| Name | Example | What it does |
|---|---|---|
| `OPENROUTER_API_KEY` | `sk-or-v1-...` | Single key for every LLM call (ranker + explainer + video). Get at https://openrouter.ai/keys |
| `TELEGRAM_BOT_TOKEN` | `8620...:AAH...` | From `@BotFather` |
| `TELEGRAM_CHAT_ID` | `1812483114` | From `https://api.telegram.org/bot<TOKEN>/getUpdates` |
| `SITE_URL` | `https://thedailypaper.akshaykumar.me` | Used in the Telegram link and as OpenRouter `HTTP-Referer` |

No `ANTHROPIC_API_KEY` — removed. All model traffic goes through OpenRouter.

---

## 2. Dokploy — deploy the site

### 2a. Create the application

1. Dokploy dashboard → **Projects → Create Project** → name it `thedailypaper`.
2. Inside the project → **Create Service → Application**.
3. **Source**:
   - Provider: **GitHub** (connect your GitHub account via Dokploy if not already).
   - Repository: `akthecoders/thedailypaper`.
   - Branch: `main`.
   - Build Path: `/` (leave as repo root — the `Dockerfile` sits at the root and copies `site/` internally).
4. **Build Type**: **Dockerfile**. Dockerfile path: `./Dockerfile`.

### 2b. Build-time arguments

Under the application's **Build** tab, set:

| Build Arg | Value |
|---|---|
| `SITE_URL` | `https://thedailypaper.akshaykumar.me` |

The Astro build reads `SITE_URL` at build time to stamp canonical URLs, RSS links, and OG tags. It is **not** a runtime env var — the nginx container serves pre-baked HTML.

### 2c. Runtime environment

None required. The container runs nginx serving pre-built static files. (Leave the Environment tab empty.)

### 2d. Domain

Under the application's **Domains** tab:

| Field | Value |
|---|---|
| Host | `thedailypaper.akshaykumar.me` |
| Path | `/` |
| Container Port | `80` |
| HTTPS | ✅ enabled |
| Certificate | **Let's Encrypt** |

Point the DNS `A` / `CNAME` for `thedailypaper.akshaykumar.me` at your Dokploy server's IP **before** enabling HTTPS, otherwise Let's Encrypt's HTTP-01 challenge fails.

### 2e. Auto-deploy

Under the application's **Deployments** tab, enable the **GitHub webhook**. Dokploy will rebuild and roll the container every time the agent pushes a new paper.

### 2f. Healthcheck

The Dockerfile already defines a `HEALTHCHECK` (`wget --spider /`). Dokploy will surface its status on the service page.

---

## 3. First deploy checklist

1. [ ] Add all four GitHub Actions secrets (above).
2. [ ] Point DNS at Dokploy server.
3. [ ] Create Dokploy app with Dockerfile build + `SITE_URL` build arg + domain.
4. [ ] **Manually trigger** the Dokploy deploy once (before enabling the webhook) to verify the build succeeds.
5. [ ] Open `https://thedailypaper.akshaykumar.me` — should show homepage with the seed entry.
6. [ ] In GitHub → **Actions tab → Daily Paper → Run workflow** to trigger a manual run.
7. [ ] Action pushes a new `.md` → Dokploy webhook rebuilds → new paper appears on the site.
8. [ ] Delete the seed entry: `rm site/src/content/papers/2026-04-18-welcome-0000.00000.md && git commit -am "remove seed" && git push`.

---

## 4. Local development

```bash
# Python agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp config/config.example.yaml config/config.yaml
cp config/interests.example.md config/interests.md   # edit this to match your interests
# populate .env (see .env in the repo for the shape)

python agent/run_daily.py --dry-run                  # no write / no Telegram
python agent/run_daily.py --date 2026-04-16          # backfill a specific day

# Astro site
cd site && npm install && npm run dev                # http://localhost:4321
```

Run the agent from the **repo root**, not from inside `agent/`. Relative paths in `config.yaml` are anchored at the repo root.

---

## 5. Swapping models

Every LLM call goes through `agent/llm.py::call_llm(model, messages)` → OpenRouter. Change the model with one line in `config/config.yaml`:

```yaml
ranker_model: "google/gemini-2.5-flash"         # cheap, fast 20-paper picker
explainer_model: "anthropic/claude-opus-4.1"    # deep 20-min explainer
video_model: "anthropic/claude-opus-4.1"        # Manim script generator
```

No code change needed. OpenRouter model catalogue: https://openrouter.ai/models

---

## 6. On-demand video generation (Phase 2)

Videos are **opt-in per paper** via a Telegram command. The flow:

```
Telegram: /video <arxiv_id>
    │
    ▼
Cloudflare Worker (webhook)
    │  (validates chat allowlist, parses command)
    ▼
GitHub API: workflow_dispatch → video.yml
    │
    ▼
generate_video.py → Claude writes Manim CE script → manim -qm
    │                 (retry up to 3× on compile errors)
    ▼
upload_video.py → MP4 to R2, stamps `videoUrl` into paper frontmatter
    │
    ▼
git push → Dokploy rebuilds → <video> tag appears on the paper page
    │
    ▼
Telegram reply: "✅ Video ready: <url>"
```

### 6a. R2 bucket setup

1. Cloudflare dashboard → **R2** → **Create bucket**: `thedailypaper-videos`.
2. Bucket settings → **Public access** → enable (or bind a custom domain like `videos.thedailypaper.akshaykumar.me`).
3. Copy the public URL base (e.g. `https://pub-<hash>.r2.dev`).
4. Dashboard → **R2 → Manage R2 API Tokens** → create a token with **Object Read & Write** scoped to that bucket. Save the Access Key ID + Secret Access Key.

### 6b. GitHub Actions secrets (add to existing list)

Add these at https://github.com/akthecoders/thedailypaper/settings/secrets/actions in addition to the 4 agent secrets:

| Name | Value |
|---|---|
| `R2_ACCOUNT_ID` | From Cloudflare dashboard URL |
| `R2_ACCESS_KEY_ID` | From step 6a.4 |
| `R2_SECRET_ACCESS_KEY` | From step 6a.4 |
| `R2_BUCKET` | `thedailypaper-videos` |
| `R2_PUBLIC_BASE_URL` | e.g. `https://pub-<hash>.r2.dev` or your custom domain |

### 6c. Deploy the Telegram webhook Worker

```bash
cd workers/telegram-video
npm install
npx wrangler login                 # one-time
npx wrangler deploy                # deploys to <name>.workers.dev
```

Then set the Worker's secrets (these are separate from GitHub secrets — they live in Cloudflare):

```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN         # paste bot token
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET    # random string, e.g. `openssl rand -hex 32`
npx wrangler secret put GH_TOKEN                   # PAT with `repo` scope, https://github.com/settings/tokens
npx wrangler secret put GH_OWNER                   # akthecoders
npx wrangler secret put GH_REPO                    # thedailypaper
npx wrangler secret put ALLOWED_CHAT_IDS           # comma-separated, e.g. 1812483114
```

### 6d. Register the Telegram webhook

One-off curl. Replace `<TOKEN>`, `<WORKER_URL>`, `<WEBHOOK_SECRET>`:

```bash
curl -sS "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=<WORKER_URL>" \
  -d "secret_token=<WEBHOOK_SECRET>"
```

Test it:

```
You → bot: /video 2604.14885
Bot → you: 🎬 Queued video render for 2604.14885 (quality=m). Takes ~5–10 min.
   ...5–10 min pass...
Bot → you: 🎬 Video ready for 2604.14885. It will appear on https://thedailypaper.akshaykumar.me after the site redeploys (~60s).
```

### 6e. Manually triggering a video

If the Worker isn't set up yet (or you prefer the UI), trigger directly from GitHub:

1. https://github.com/akthecoders/thedailypaper/actions → **Generate Video** → **Run workflow**
2. Fill `arxiv_id` (e.g. `2604.14885`), leave `quality` as `m`, optional `notify_chat_id`.
3. Watch the run. ~7 min total (install ~2min + render ~3–5min + upload+commit).

### 6f. Costs

| Item | Rough cost |
|---|---|
| Claude Opus for Manim script (~8k tokens/run × retries) | ~$0.30/video |
| GitHub Actions minutes | ~6 min/video; 2000 free/month = ~300 videos/month headroom |
| R2 storage + egress | 10GB free tier; each MP4 ~5MB = 2000 videos before paying |
| Cloudflare Worker | 100k requests/day free — more than enough |

## Email subscriptions

Reader emails ship through a Cloudflare Worker (`workers/subscribe`) backed by
Resend Audiences. See `docs/superpowers/specs/2026-04-20-email-subscriptions-design.md`
for full architecture and `docs/superpowers/plans/2026-04-20-email-subscriptions.md`
for the task-by-task implementation plan.

### One-time setup

1. **Resend** — create account at resend.com, generate an API key with Full Access.
2. **Sending domain** — in Resend → Domains, add `thedailypaper.akshaykumar.me`.
   Copy the SPF TXT and two DKIM CNAMEs into your DNS provider. Wait for verification.
3. **DMARC record** — add TXT `_dmarc.thedailypaper.akshaykumar.me` with value
   `v=DMARC1; p=none; rua=mailto:akshaykumar@grainsetu.com`.
4. **Audience** — Resend → Audiences → create "Daily Paper Readers" and copy the
   audience ID (UUID). Also create a **throwaway test audience**
   "Daily Paper Readers (test)" — used for the first live send.
5. **Turnstile** — Cloudflare dashboard → Turnstile → create a site for
   `thedailypaper.akshaykumar.me`, copy sitekey + secret key.
6. **Worker KV namespace** — from `workers/subscribe/`:
   ```bash
   npx wrangler kv:namespace create SUBSCRIBE_CACHE
   ```
   Paste the returned `id` into `workers/subscribe/wrangler.toml` replacing
   `KV_NAMESPACE_ID_HERE`.
7. **Subscription secret** — generate: `openssl rand -hex 32`
8. **Deploy the Worker:**
   ```bash
   cd workers/subscribe
   npx wrangler secret put RESEND_API_KEY
   npx wrangler secret put RESEND_AUDIENCE_ID        # use the TEST audience ID at first
   npx wrangler secret put SUBSCRIPTION_SECRET
   npx wrangler secret put TURNSTILE_SECRET_KEY
   npx wrangler deploy
   ```
   Copy the returned worker URL (e.g. `https://subscribe.<subdomain>.workers.dev`).

9. **Astro site env** — set `PUBLIC_SUBSCRIBE_WORKER_URL=<worker URL>` in:
   - `site/.env` for local dev
   - Dokploy environment variables for production

10. **GitHub Actions:**
    - Repo Settings → Secrets: `RESEND_API_KEY`, `RESEND_AUDIENCE_ID` (test audience at first)
    - Repo Settings → Variables: `NEWSLETTER_ENABLED=false` (flip to `true` when ready)

### Capacity note

Resend free tier: **3,000 emails/month, 100/day**. With Tue+Fri cadence and N
subscribers, monthly send volume ≈ 8N. Free tier supports ~350 subscribers with
the monthly cap, but the daily cap will bite first — upgrade the Resend plan
before your audience crosses ~100 subscribers so a single Tue or Fri send
doesn't hit the 100/day ceiling.

### Rollout

1. Deploy worker with the TEST audience ID.
2. Sign up your own email via the form, confirm — proves the end-to-end signup
   flow works. `curl $WORKER_URL/count` should return `{"count":1}`.
3. Set `NEWSLETTER_ENABLED=true` in GitHub Actions variables.
4. Trigger a manual workflow run with `--dry-newsletter` to inspect the HTML:
   ```bash
   gh workflow run "Daily Paper"
   ```
   (Dry-newsletter requires passing the flag through the workflow; easiest is to
   run locally for the dry render:
   `python agent/run_daily.py --date YYYY-MM-DD --dry-newsletter > email.html`
   and paste the HTML into https://www.mail-tester.com/ — aim for ≥ 8/10.)
5. First live send: keep `RESEND_AUDIENCE_ID` pointing at the test audience.
   Trigger the workflow, verify the email lands in your inbox with correct subject,
   from address, reply-to, and unsubscribe link.
6. Promote to real audience: update `RESEND_AUDIENCE_ID` in both the Worker
   secret (`wrangler secret put RESEND_AUDIENCE_ID`, then `wrangler deploy`) and
   the GitHub Actions secret. Announce the `/subscribe` URL.

### Local dev

For local worker testing:
- Create `workers/subscribe/.dev.vars` with placeholder values (gitignored).
  The bypass logic skips Turnstile when the secret is `"test"` or empty.
- `cd workers/subscribe && npx wrangler dev --local --port 8787` to run locally.
- Astro: `cd site && npm run dev` — the SubscribeForm will POST to whatever
  `PUBLIC_SUBSCRIBE_WORKER_URL` points at.

Practical ceiling: ~300 videos/month on pure free tier, bounded by Claude spend at ~$90/month if you render all of them at Opus quality. Drop to `anthropic/claude-haiku-4.5` for `video_model` to roughly halve that.
