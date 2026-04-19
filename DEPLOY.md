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
video_model: "anthropic/claude-opus-4.1"        # Phase 2 Manim generation
```

No code change needed. OpenRouter model catalogue: https://openrouter.ai/models
