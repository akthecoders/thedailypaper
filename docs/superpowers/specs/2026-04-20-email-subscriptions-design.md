# Email Subscriptions — Design Spec

**Date:** 2026-04-20
**Status:** Draft · pending review
**Owner:** Akshay

## Goal

Let readers subscribe to `thedailypaper.akshaykumar.me` and receive an email each time a new paper is published (Tue + Fri cadence). Email arrives in the same editorial voice as the site, with one-click unsubscribe, replies landing in Akshay's inbox, and a subscriber count badge on the site.

## Decisions (resolved during brainstorm)

| # | Decision | Choice |
|---|---|---|
| 1 | Storage + signup backend | Resend Audiences + Cloudflare Worker |
| 2 | Opt-in flow | Double opt-in |
| 3 | Cadence | Per-paper (sent on publish) |
| 4 | Features in v1 | Unsubscribe, reply-to, subscriber count badge, archive link, open+click tracking |
| 5 | Form placement | Homepage hero + site-wide footer + dedicated `/subscribe` page |
| 6 | Email template | Editorial (matches site — warm cream, Fraunces/Newsreader, terracotta TL;DR rule) |
| 7 | Subject line | Paper title only (no prefix) |
| 8 | Sender identity | `The Daily Paper <papers@thedailypaper.akshaykumar.me>` |

Explicitly **out of scope** for v1: feedback buttons in email (thumbs up/down), digest mode, preference center, referral program.

## Architecture

```
┌───────────────────────┐        ┌────────────────────────────┐
│ Astro site (Dokploy)  │        │ Cloudflare Worker           │
│  - <SubscribeForm/>   │ POST → │  POST /subscribe            │
│  - /subscribe         │        │    → signs JWT(email, ts)   │
│  - <SubscriberBadge/> │ GET  → │    → Resend: send confirm   │
│                       │ ─/count┤  GET  /confirm?token        │
└───────────────────────┘        │    → verify JWT → Resend:   │
                                 │      Contacts.create        │
                                 │  GET  /count                │
                                 │    → Resend: Audience size  │
                                 │      (cached 10 min)        │
                                 └────────────────────────────┘

┌───────────────────────────────────────┐
│ Python agent (GitHub Actions cron)     │
│  run_daily.py                          │
│    → fetch → rank → explain → write    │
│    → notify_telegram                   │
│    → send_newsletter   ← NEW           │
│         Resend.Broadcasts.create()     │
│         Resend.Broadcasts.send()       │
└───────────────────────────────────────┘
```

**Five new pieces:**

1. Cloudflare Worker at `workers/subscribe/` (mirrors `workers/telegram-video/` layout).
2. Astro component `site/src/components/SubscribeForm.astro` + page `site/src/pages/subscribe.astro` + badge `site/src/components/SubscriberBadge.astro`.
3. Python module `agent/send_newsletter.py` + email template at `agent/templates/newsletter.html` and `newsletter.txt`.
4. `run_daily.py` wiring — new step after `write_post`, before `notify_telegram`.
5. DNS records on `thedailypaper.akshaykumar.me` for Resend sending domain (SPF, DKIM, DMARC).

## Component 1 — Cloudflare Worker (`workers/subscribe`)

**Routes:**

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/subscribe` | Body: `{email: string}`. Validates format, creates signed JWT `{email, ts}` with 48h TTL, sends confirmation email via Resend (template `confirm.html`, link to `/confirm?token=…`). Returns `{status: "pending"}`. |
| `GET` | `/confirm?token=…` | Verifies JWT signature + TTL. On success, calls `Resend.Contacts.create({email, audienceId, unsubscribed: false})`. Responds with HTML page (minimal, on-brand) saying "You're subscribed." On failure (expired/invalid), shows "This link is expired — resubscribe at `/subscribe`." |
| `GET` | `/count` | Fetches `Resend.Contacts.list({audienceId})`, counts non-unsubscribed. Cached in Worker KV for 10 min. Returns `{count: number}` with `Cache-Control: public, max-age=600`. |

**Double opt-in via stateless JWT** — we don't persist pending signups. JWT carries the email + timestamp, signed with `SUBSCRIPTION_SECRET`. If the user never confirms, the token expires silently. No cleanup job needed.

**Secrets** (via `wrangler secret put`): `RESEND_API_KEY`, `RESEND_AUDIENCE_ID`, `SUBSCRIPTION_SECRET`, `SITE_URL`.

**Spam protection:** Cloudflare Turnstile on the form (invisible mode), honeypot field (`<input name="website" class="sr-only">`), rate limit 10 req/min/IP via CF's built-in rate limiting rules.

**Error handling:**
- Invalid email → 400 `{error: "invalid_email"}`
- Already confirmed → 200 `{status: "already_subscribed"}` (don't leak whether email exists — return the same success shape as new signup to prevent enumeration)
- Resend API failure → 502 `{error: "upstream_unavailable"}`, logged to Worker analytics

## Component 2 — Astro site

**`SubscribeForm.astro`** — single reusable component, three contexts:

- `variant="hero"` — homepage hero, larger, with supporting copy
- `variant="footer"` — compact, one-line, in site footer
- `variant="page"` — used on `/subscribe`, medium size with supporting copy above

All variants: progressive-enhancement form. `<form action="{PUBLIC_SUBSCRIBE_WORKER_URL}/subscribe" method="POST">` works without JS (redirects to a worker-rendered thank-you page). JS-enhanced path intercepts submit, does `fetch()`, swaps in an inline "check your email" confirmation without navigation.

**`/subscribe.astro`** — dedicated page: headline, 2-3 sentence pitch, form (page variant), small FAQ ("how often?", "can I unsubscribe anytime?", "will you share my email?").

**`SubscriberBadge.astro`** — renders "Join N readers" wherever dropped in. Fetches `/count` at **build time** via top-level `await` in Astro frontmatter. Graceful fallback: if fetch fails, render nothing (no "Join 0 readers" embarrassment). Site rebuilds on every paper commit, so count stays fresh within ~3 days. Badge placement: below the hero form and on `/subscribe`.

**Footer update** — `site/src/components/Footer.astro` (check if exists; otherwise add in `BaseLayout.astro`) gets compact form variant.

**Env:** new `PUBLIC_SUBSCRIBE_WORKER_URL` read in Astro at build time.

## Component 3 — Python newsletter module

**`agent/send_newsletter.py`**

```python
def send_newsletter(
    winner: dict,
    explainer: dict,  # {tldr, hook, body}
    post_url: str,
    api_key: str,
    audience_id: str,
    from_address: str,
) -> None
```

Responsibilities:
1. Load `agent/templates/newsletter.html` and `newsletter.txt`, substitute variables.
2. Call `Resend.Broadcasts.create({audience_id, from, subject, html, text, reply_to})`.
3. Call `Resend.Broadcasts.send({broadcast_id})`.
4. Log broadcast ID to stdout for audit trail.

**Failure mode:** wrapped in try/except in `run_daily.py`. If newsletter send fails, log the error, continue to Telegram ping. Never fail the pipeline over email.

**Subject line:** `winner["title"]` only.
**Reply-To:** `akshaykumar@grainsetu.com` (goes to Akshay's personal inbox).
**From:** `The Daily Paper <papers@thedailypaper.akshaykumar.me>`.

## Component 4 — Email templates

**`agent/templates/newsletter.html`** — Editorial design (Option A from brainstorm). Hand-written inline CSS, table-based layout for Outlook compatibility. Sections, in order:

1. Masthead: "THE DAILY PAPER" / date, bottom border.
2. Paper title (Fraunces fallback to Georgia, 28px, weight 600).
3. Meta line: "by {authors[:2]} et al. · {primary_category}".
4. TL;DR — terracotta left rule, italic, 17px.
5. Hook paragraph — first 2-3 sentences of the explainer body.
6. CTA button — "Read the full explainer →" → `{post_url}`.
7. Divider.
8. Footer: archive link, reply prompt, unsubscribe (Resend's one-click variable), view-in-browser link.

**`newsletter.txt`** — plain-text equivalent. Required by RFC and boosts deliverability.

**`confirm.html`** — shorter template used by the Worker: masthead, single sentence ("Confirm your subscription to The Daily Paper"), CTA button to `/confirm?token=…`, small footer explaining "If you didn't sign up, ignore this email — the link expires in 48 hours." **This lives in the Worker codebase**, not the agent.

**Web-font strategy in email:** `@import` Fraunces/Newsreader from Google Fonts in `<head>`, but always declare Georgia fallback inline on every heading. ~60% of clients will render the web font; the rest get Georgia, which is close enough in character.

## Component 5 — DNS + Resend setup

One-time manual setup (documented in `DEPLOY.md` update):

1. In Resend dashboard: create sending domain `thedailypaper.akshaykumar.me`, get DNS records (SPF, DKIM — two CNAMEs + one TXT).
2. Add records in domain DNS provider. Wait for verification.
3. Create Audience "Daily Paper Readers", copy ID.
4. Generate API key scoped to Audience + Broadcasts.
5. Add DMARC record: `v=DMARC1; p=none; rua=mailto:akshaykumar@grainsetu.com`.

## Data flow — end-to-end signup

```
1. User types email in footer form, hits subscribe.
2. (JS path) fetch POST /subscribe {email} → Worker
   (No-JS path) form submits to Worker, Worker renders thank-you page.
3. Worker validates email format + Turnstile token.
4. Worker creates JWT(email, iat=now) with 48h TTL.
5. Worker calls Resend.Emails.send() with confirm.html, link = SITE_URL + /confirm?token=JWT.
6. Worker responds {status: "pending"}.
7. UI swaps in "Check your inbox to confirm."
8. User opens email, clicks confirm button.
9. Browser navigates to WORKER_URL/confirm?token=…
10. Worker verifies JWT sig + TTL.
11. Worker calls Resend.Contacts.create({email, audienceId, unsubscribed: false}).
12. Worker returns HTML page "You're subscribed."
```

## Data flow — end-to-end paper send

```
1. run_daily.py runs on Tue/Fri at 01:30 UTC.
2. Existing steps complete: fetch → rank → explain → write_post.
3. NEW: send_newsletter(winner, explainer, post_url, …) called.
4. Module loads HTML + text templates, substitutes {title, authors, tldr, hook, post_url}.
5. Resend.Broadcasts.create({audience_id, subject=title, from, html, text, reply_to}).
6. Resend.Broadcasts.send({broadcast_id}) — Resend batches + delivers.
7. Log broadcast_id to workflow output.
8. Existing step: notify_telegram (unchanged).
9. Existing step: git commit + push.
```

## Testing strategy

The project has no test suite. Validation path:

- **Worker:** `wrangler dev` locally. Hit `POST /subscribe` with curl, verify confirmation email received, click link, verify contact appears in Resend Audience dashboard.
- **Astro:** `npm run dev`, verify form on home + footer + `/subscribe`, submit, verify Worker receives request (watch `wrangler tail`).
- **Newsletter send:** new `--skip-newsletter` flag on `run_daily.py` (default: send). Add `--dry-newsletter` that renders the HTML + text to stdout without calling Resend. Before first real send: run `--dry-newsletter`, paste HTML into Litmus or Mail Tester to check rendering + spam score.
- **First send:** use a throwaway Audience with 2-3 test emails (yours + aliases) for the first Tue/Fri run. Promote to real Audience once confirmed clean.

## Rollout plan

1. Create Resend account + sending domain + DNS records. (One-time, manual.)
2. Ship Worker to Cloudflare with secrets.
3. Ship Astro changes (form + subscribe page + badge). No send yet.
4. Smoke-test signup → confirm end-to-end with personal email.
5. Add `send_newsletter.py` behind a feature flag (`NEWSLETTER_ENABLED=false` initially).
6. Run `run_daily.py --dry-newsletter` for next publish; inspect output.
7. Flip `NEWSLETTER_ENABLED=true`, run with test Audience.
8. Swap test Audience ID for real one, announce subscribe URL.

## Open questions / deferred decisions

- **Sending volume limits:** Resend free tier is 3k/month, 100/day. For Tue+Fri sends to N subscribers, limit is 100 per send on free. Need to upgrade before crossing 100 subscribers. Note in `DEPLOY.md`.
- **Broadcasts vs individual sends:** Using Broadcasts API. If Resend Broadcasts has rate limits that bite, fall back to `Emails.send()` in a loop with `bcc` batches of 50.
- **Future: email-only content.** Out of scope v1. Trivial extension once pipeline exists.

## Files touched (estimate)

**New:**
- `workers/subscribe/src/index.ts`
- `workers/subscribe/wrangler.toml`
- `workers/subscribe/templates/confirm.html`
- `site/src/components/SubscribeForm.astro`
- `site/src/components/SubscriberBadge.astro`
- `site/src/pages/subscribe.astro`
- `agent/send_newsletter.py`
- `agent/templates/newsletter.html`
- `agent/templates/newsletter.txt`

**Modified:**
- `site/src/layouts/BaseLayout.astro` (add footer form)
- `site/src/pages/index.astro` (hero form + badge)
- `agent/run_daily.py` (call send_newsletter)
- `agent/config_loader.py` (new env vars: RESEND_API_KEY, RESEND_AUDIENCE_ID, NEWSLETTER_ENABLED)
- `config/config.example.yaml` (document new env vars)
- `.github/workflows/daily.yml` (pass new secrets)
- `DEPLOY.md` (Resend setup + DNS instructions)
- `README.md` (subscribe link)
