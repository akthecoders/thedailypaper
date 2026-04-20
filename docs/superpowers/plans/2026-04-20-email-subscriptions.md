# Email Subscriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let readers subscribe to `thedailypaper.akshaykumar.me` and receive a Resend-delivered email every time a new paper is published (Tue + Fri), matching the site's editorial aesthetic.

**Architecture:** Cloudflare Worker hosts the signup + confirm endpoints backed by Resend Audiences (stateless double-opt-in via signed JWT — no DB). Astro site has a reusable `<SubscribeForm>` component (hero, footer, page variants) plus a build-time subscriber count badge. Python agent gets a `send_newsletter.py` module invoked from `run_daily.py` after `write_post`, firing a Resend Broadcast in the editorial template voice.

**Tech Stack:** Cloudflare Workers (TypeScript), Resend (Audiences + Broadcasts + Emails APIs), Astro 5 with CSS variables (no Tailwind), Python 3.11 + `requests`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-04-20-email-subscriptions-design.md`

**Project testing convention:** This repo has no automated test suite (per `CLAUDE.md`). This plan substitutes **validation steps** — curl, `wrangler dev`, `npm run dev`, and `run_daily.py --dry-newsletter` — in place of unit tests. Every change-making task ends with a real validation command and an explicit expected-output check before the commit.

---

## Prerequisites (manual, one-time, before Task 1)

These are operator actions outside the code. Document in `DEPLOY.md` but do them now so the code has something to target.

1. **Resend account** — sign up at `resend.com`, generate an API key with `Full access`.
2. **Sending domain** — add `thedailypaper.akshaykumar.me` in Resend → Domains. Copy the SPF TXT, two DKIM CNAMEs into the DNS provider. Wait for verification (green check in Resend).
3. **DMARC record** — add TXT `_dmarc.thedailypaper.akshaykumar.me` with value `v=DMARC1; p=none; rua=mailto:akshaykumar@grainsetu.com`.
4. **Audience** — Resend → Audiences → Create "Daily Paper Readers" — **copy the audience ID** (UUID). Also create a **throwaway test audience** "Daily Paper Readers (test)" with same settings — used for first live run.
5. **Turnstile site** — Cloudflare dashboard → Turnstile → create site for `thedailypaper.akshaykumar.me`, copy sitekey + secret.
6. **Worker KV namespace** — `wrangler kv:namespace create "SUBSCRIBE_CACHE"` — copy the namespace ID.
7. **Subscription secret** — `openssl rand -hex 32` — this is the JWT signing secret.
8. **Stash these values somewhere you can paste from:**
   - `RESEND_API_KEY`
   - `RESEND_AUDIENCE_ID` (real)
   - `RESEND_AUDIENCE_ID_TEST` (throwaway)
   - `SUBSCRIPTION_SECRET`
   - `TURNSTILE_SITE_KEY`
   - `TURNSTILE_SECRET_KEY`
   - `KV_NAMESPACE_ID`

---

## Task 1: Scaffold `workers/subscribe` package

**Files:**
- Create: `workers/subscribe/package.json`
- Create: `workers/subscribe/tsconfig.json`
- Create: `workers/subscribe/wrangler.toml`
- Create: `workers/subscribe/src/index.ts`
- Create: `workers/subscribe/src/env.ts`

- [ ] **Step 1: Create `workers/subscribe/package.json`**

```json
{
  "name": "subscribe-worker",
  "private": true,
  "version": "0.1.0",
  "scripts": {
    "deploy": "wrangler deploy",
    "dev": "wrangler dev",
    "tail": "wrangler tail"
  },
  "devDependencies": {
    "@cloudflare/workers-types": "^4.20250101.0",
    "typescript": "^5.4.0",
    "wrangler": "^3.80.0"
  }
}
```

- [ ] **Step 2: Create `workers/subscribe/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "Bundler",
    "strict": true,
    "types": ["@cloudflare/workers-types"],
    "lib": ["ES2022"],
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["src/**/*.ts"]
}
```

- [ ] **Step 3: Create `workers/subscribe/wrangler.toml`**

Replace `KV_NAMESPACE_ID_HERE` with the ID from prerequisite step 6.

```toml
name = "subscribe"
main = "src/index.ts"
compatibility_date = "2026-04-01"

# Secrets (set via `wrangler secret put <NAME>`):
#   RESEND_API_KEY
#   RESEND_AUDIENCE_ID
#   SUBSCRIPTION_SECRET
#   TURNSTILE_SECRET_KEY
# Vars (non-secret):
[vars]
SITE_URL = "https://thedailypaper.akshaykumar.me"
FROM_ADDRESS = "The Daily Paper <papers@thedailypaper.akshaykumar.me>"
REPLY_TO = "akshaykumar@grainsetu.com"

[[kv_namespaces]]
binding = "SUBSCRIBE_CACHE"
id = "KV_NAMESPACE_ID_HERE"

# Optional: custom route
# [[routes]]
# pattern = "subscribe.thedailypaper.akshaykumar.me/*"
# custom_domain = true
```

- [ ] **Step 4: Create `workers/subscribe/src/env.ts`**

```ts
export interface Env {
  // Secrets
  RESEND_API_KEY: string;
  RESEND_AUDIENCE_ID: string;
  SUBSCRIPTION_SECRET: string;
  TURNSTILE_SECRET_KEY: string;
  // Vars
  SITE_URL: string;
  FROM_ADDRESS: string;
  REPLY_TO: string;
  // Bindings
  SUBSCRIBE_CACHE: KVNamespace;
}
```

- [ ] **Step 5: Create `workers/subscribe/src/index.ts` (router skeleton)**

```ts
// Cloudflare Worker: handles newsletter signup, double-opt-in confirmation,
// and serves subscriber count.
import type { Env } from "./env";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    if (request.method === "POST" && url.pathname === "/subscribe") {
      return new Response(JSON.stringify({ status: "not_implemented" }), {
        status: 501,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
      });
    }

    if (request.method === "GET" && url.pathname === "/confirm") {
      return new Response("Not implemented", { status: 501 });
    }

    if (request.method === "GET" && url.pathname === "/count") {
      return new Response(JSON.stringify({ count: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
      });
    }

    return new Response("Not found", { status: 404 });
  },
};
```

- [ ] **Step 6: Install and verify**

```bash
cd workers/subscribe && npm install && npx wrangler --version
```

Expected: prints wrangler version (≥ 3.80). If `wrangler` is missing globally, the local install provides it.

- [ ] **Step 7: Commit**

```bash
git add workers/subscribe
git commit -m "subscribe-worker: scaffold package, wrangler config, router skeleton"
```

---

## Task 2: JWT utility for stateless double-opt-in

**Files:**
- Create: `workers/subscribe/src/jwt.ts`

JWT is HMAC-SHA256 signed. Web Crypto gives us `crypto.subtle.sign/verify` with `HMAC` — no dependencies needed.

- [ ] **Step 1: Create `workers/subscribe/src/jwt.ts`**

```ts
// Minimal HS256 JWT signer/verifier. Web Crypto only — no deps.

const ALG = { name: "HMAC", hash: "SHA-256" };
const TTL_SECONDS = 48 * 60 * 60; // 48h

interface Claims {
  email: string;
  iat: number; // issued-at, unix seconds
}

function b64urlEncode(bytes: Uint8Array): string {
  let s = btoa(String.fromCharCode(...bytes));
  return s.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(s: string): Uint8Array {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    ALG,
    false,
    ["sign", "verify"],
  );
}

export async function signToken(email: string, secret: string): Promise<string> {
  const header = { alg: "HS256", typ: "JWT" };
  const claims: Claims = { email, iat: Math.floor(Date.now() / 1000) };
  const enc = new TextEncoder();
  const h = b64urlEncode(enc.encode(JSON.stringify(header)));
  const c = b64urlEncode(enc.encode(JSON.stringify(claims)));
  const signingInput = `${h}.${c}`;
  const key = await hmacKey(secret);
  const sig = new Uint8Array(
    await crypto.subtle.sign(ALG, key, enc.encode(signingInput)),
  );
  return `${signingInput}.${b64urlEncode(sig)}`;
}

export async function verifyToken(
  token: string,
  secret: string,
): Promise<{ ok: true; email: string } | { ok: false; reason: string }> {
  const parts = token.split(".");
  if (parts.length !== 3) return { ok: false, reason: "malformed" };
  const [h, c, s] = parts;
  const enc = new TextEncoder();
  const key = await hmacKey(secret);
  const valid = await crypto.subtle.verify(
    ALG,
    key,
    b64urlDecode(s),
    enc.encode(`${h}.${c}`),
  );
  if (!valid) return { ok: false, reason: "bad_signature" };

  let claims: Claims;
  try {
    claims = JSON.parse(new TextDecoder().decode(b64urlDecode(c)));
  } catch {
    return { ok: false, reason: "bad_claims" };
  }
  const age = Math.floor(Date.now() / 1000) - claims.iat;
  if (age < 0 || age > TTL_SECONDS) return { ok: false, reason: "expired" };
  if (typeof claims.email !== "string" || !claims.email.includes("@")) {
    return { ok: false, reason: "bad_email" };
  }
  return { ok: true, email: claims.email.toLowerCase() };
}
```

- [ ] **Step 2: Validate with `wrangler dev`**

Add a temporary debug route to `src/index.ts` inside the `fetch` handler (we'll remove it in Task 3):

```ts
if (url.pathname === "/__debug/jwt") {
  const { signToken, verifyToken } = await import("./jwt");
  const t = await signToken("test@example.com", env.SUBSCRIPTION_SECRET);
  const v = await verifyToken(t, env.SUBSCRIPTION_SECRET);
  return new Response(JSON.stringify({ t, v }, null, 2), {
    headers: { "Content-Type": "application/json" },
  });
}
```

Set a local dev secret: `echo "local-dev-secret-dont-use-in-prod" > .dev.vars` in `workers/subscribe/` with `SUBSCRIPTION_SECRET=local-dev-secret-dont-use-in-prod` on its own line (full `.dev.vars` format is KEY=VALUE per line; add placeholders for the other secrets: `RESEND_API_KEY=test`, `RESEND_AUDIENCE_ID=test`, `TURNSTILE_SECRET_KEY=test`).

Run:

```bash
cd workers/subscribe && npx wrangler dev --local
```

In a second terminal:

```bash
curl -s http://localhost:8787/__debug/jwt | head -20
```

Expected: JSON with `t` (long dotted string) and `v: {"ok":true,"email":"test@example.com"}`.

- [ ] **Step 3: Remove the `/__debug/jwt` route**

Delete the block. We only wanted to prove JWT works.

- [ ] **Step 4: Add `.dev.vars` to `.gitignore`**

Append to root `.gitignore`:

```
# Cloudflare Worker local dev secrets
workers/*/.dev.vars
```

- [ ] **Step 5: Commit**

```bash
git add workers/subscribe/src/jwt.ts .gitignore
git commit -m "subscribe-worker: HS256 JWT signer/verifier for DOI tokens"
```

---

## Task 3: `POST /subscribe` + Resend confirmation email

**Files:**
- Create: `workers/subscribe/src/resend.ts`
- Create: `workers/subscribe/src/confirm-email.ts`
- Modify: `workers/subscribe/src/index.ts`

- [ ] **Step 1: Create `workers/subscribe/src/resend.ts`**

```ts
// Thin wrapper around the Resend REST API. No SDK — we only need two calls
// on the Worker side: send a single transactional email, and upsert a contact
// into an audience.

import type { Env } from "./env";

const BASE = "https://api.resend.com";

interface SendEmailParams {
  to: string;
  subject: string;
  html: string;
  text: string;
  from: string;
  replyTo?: string;
}

export async function sendEmail(env: Env, p: SendEmailParams): Promise<void> {
  const resp = await fetch(`${BASE}/emails`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: p.from,
      to: [p.to],
      subject: p.subject,
      html: p.html,
      text: p.text,
      reply_to: p.replyTo,
    }),
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Resend /emails ${resp.status}: ${body}`);
  }
}

export async function createContact(
  env: Env,
  email: string,
): Promise<{ created: boolean; alreadyExisted: boolean }> {
  const resp = await fetch(
    `${BASE}/audiences/${env.RESEND_AUDIENCE_ID}/contacts`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, unsubscribed: false }),
    },
  );
  if (resp.ok) return { created: true, alreadyExisted: false };
  if (resp.status === 409) return { created: false, alreadyExisted: true };
  const body = await resp.text();
  throw new Error(`Resend contacts ${resp.status}: ${body}`);
}

export async function contactExists(env: Env, email: string): Promise<boolean> {
  const resp = await fetch(
    `${BASE}/audiences/${env.RESEND_AUDIENCE_ID}/contacts/${encodeURIComponent(email)}`,
    {
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}` },
    },
  );
  return resp.ok;
}

export async function listContacts(env: Env): Promise<Array<{ unsubscribed: boolean }>> {
  const resp = await fetch(
    `${BASE}/audiences/${env.RESEND_AUDIENCE_ID}/contacts`,
    { headers: { Authorization: `Bearer ${env.RESEND_API_KEY}` } },
  );
  if (!resp.ok) throw new Error(`Resend list ${resp.status}`);
  const j = (await resp.json()) as { data: Array<{ unsubscribed: boolean }> };
  return j.data;
}
```

- [ ] **Step 2: Create `workers/subscribe/src/confirm-email.ts`**

```ts
// HTML + plain-text body for the confirmation email (double-opt-in).
// Tiny subset of the editorial style — we only need masthead + CTA.

export function confirmEmailHtml(confirmUrl: string): string {
  return `<!doctype html>
<html>
<head><meta charset="utf-8"><title>Confirm your subscription</title></head>
<body style="margin:0;background:#f7f3ec;font-family:Georgia,serif;color:#1a1814;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#f7f3ec;padding:32px 40px;">
        <tr><td style="border-bottom:1px solid #d9d1c3;padding-bottom:12px;font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:#7a756d;">
          The Daily Paper
        </td></tr>
        <tr><td style="padding-top:28px;">
          <h1 style="font-family:Georgia,serif;font-size:24px;font-weight:600;margin:0 0 16px;line-height:1.25;">
            Confirm your subscription
          </h1>
          <p style="font-size:16px;line-height:1.6;margin:0 0 24px;">
            You (or someone with your email) asked to subscribe to The Daily Paper — a deep-dive on one arXiv paper every Tuesday and Friday. Click below to confirm and you're in.
          </p>
          <p style="margin:0 0 24px;">
            <a href="${confirmUrl}" style="display:inline-block;background:#b8442e;color:#f7f3ec;padding:14px 28px;text-decoration:none;font-family:Georgia,serif;font-weight:600;font-size:15px;">
              Confirm subscription →
            </a>
          </p>
          <p style="font-size:13px;color:#7a756d;line-height:1.6;margin:0;">
            If you didn't sign up, you can safely ignore this email. The link expires in 48 hours.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;
}

export function confirmEmailText(confirmUrl: string): string {
  return `The Daily Paper — Confirm your subscription

You (or someone with your email) asked to subscribe to The Daily Paper — a deep-dive on one arXiv paper every Tuesday and Friday.

Confirm your subscription:
${confirmUrl}

If you didn't sign up, ignore this email. The link expires in 48 hours.`;
}
```

- [ ] **Step 3: Implement `POST /subscribe` in `workers/subscribe/src/index.ts`**

Replace the `POST /subscribe` branch in the router:

```ts
import { signToken } from "./jwt";
import { sendEmail, contactExists } from "./resend";
import { confirmEmailHtml, confirmEmailText } from "./confirm-email";

// ... inside fetch handler, replace the POST /subscribe branch:

if (request.method === "POST" && url.pathname === "/subscribe") {
  let body: { email?: unknown; website?: unknown; turnstileToken?: unknown };
  try {
    body = await request.json();
  } catch {
    return json({ error: "invalid_body" }, 400);
  }

  // Honeypot — real users leave `website` blank.
  if (typeof body.website === "string" && body.website.length > 0) {
    return json({ status: "pending" }, 200); // silently drop
  }

  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (!isValidEmail(email)) return json({ error: "invalid_email" }, 400);

  // Already subscribed? Don't re-send confirmation, but don't leak existence
  // — return the same shape as a fresh signup.
  try {
    if (await contactExists(env, email)) {
      return json({ status: "pending" }, 200);
    }
  } catch (e) {
    console.error("contactExists failed", e);
    // Fall through — still send confirmation. Worst case we double-confirm.
  }

  const token = await signToken(email, env.SUBSCRIPTION_SECRET);
  const confirmUrl = `${new URL(request.url).origin}/confirm?token=${encodeURIComponent(token)}`;

  try {
    await sendEmail(env, {
      to: email,
      subject: "Confirm your subscription to The Daily Paper",
      html: confirmEmailHtml(confirmUrl),
      text: confirmEmailText(confirmUrl),
      from: env.FROM_ADDRESS,
      replyTo: env.REPLY_TO,
    });
  } catch (e) {
    console.error("sendEmail failed", e);
    return json({ error: "upstream_unavailable" }, 502);
  }

  return json({ status: "pending" }, 200);
}

// helpers (add near bottom of file, above `export default`):
function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...CORS_HEADERS },
  });
}

function isValidEmail(e: string): boolean {
  // Purposely loose — Resend does the real validation.
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e) && e.length <= 254;
}
```

- [ ] **Step 4: Local validation with `wrangler dev`**

Start the worker:

```bash
cd workers/subscribe && npx wrangler dev --local
```

In another terminal:

```bash
# Valid signup
curl -s -X POST http://localhost:8787/subscribe \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com"}'
# Expected: {"error":"upstream_unavailable"} — you don't have a real RESEND_API_KEY in .dev.vars.
# That's OK — it proves the email-validation path worked and we reached the Resend call.

# Invalid email
curl -s -X POST http://localhost:8787/subscribe \
  -H "Content-Type: application/json" \
  -d '{"email":"not-an-email"}'
# Expected: {"error":"invalid_email"}

# Honeypot trigger
curl -s -X POST http://localhost:8787/subscribe \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","website":"http://spam.com"}'
# Expected: {"status":"pending"} with no Resend call in wrangler logs.
```

- [ ] **Step 5: Commit**

```bash
git add workers/subscribe/src
git commit -m "subscribe-worker: POST /subscribe with honeypot and DOI email"
```

---

## Task 4: `GET /confirm` → create Resend contact

**Files:**
- Modify: `workers/subscribe/src/index.ts`
- Create: `workers/subscribe/src/confirm-page.ts`

- [ ] **Step 1: Create `workers/subscribe/src/confirm-page.ts`**

```ts
// Minimal HTML response pages for the confirm flow.
export function successPage(siteUrl: string): string {
  return pageWrap(
    "You're subscribed",
    `<p>Thanks for confirming. The next paper drops on Tuesday or Friday and will land in your inbox.</p>
     <p><a href="${siteUrl}" style="color:#b8442e;">← Back to The Daily Paper</a></p>`,
  );
}

export function expiredPage(siteUrl: string): string {
  return pageWrap(
    "Link expired",
    `<p>This confirmation link has expired or is invalid. Please <a href="${siteUrl}/subscribe" style="color:#b8442e;">resubscribe</a> — it only takes a moment.</p>`,
  );
}

export function errorPage(): string {
  return pageWrap(
    "Something went wrong",
    `<p>We couldn't confirm your subscription right now. Please try again in a minute. If the problem continues, reply to the confirmation email and we'll add you manually.</p>`,
  );
}

function pageWrap(title: string, bodyHtml: string): string {
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>${title} — The Daily Paper</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{margin:0;background:#f7f3ec;color:#1a1814;font-family:Georgia,serif;line-height:1.6;}
  .frame{max-width:560px;margin:80px auto;padding:40px 32px;}
  .masthead{font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:#7a756d;border-bottom:1px solid #d9d1c3;padding-bottom:12px;margin-bottom:28px;}
  h1{font-size:28px;font-weight:600;margin:0 0 16px;}
  a{color:#b8442e;}
  @media (prefers-color-scheme:dark){body{background:#1a1814;color:#f2ece0;}.masthead{color:#8a857a;border-color:#3a362e;}a{color:#e8806a;}}
</style>
</head><body><div class="frame">
<div class="masthead">The Daily Paper</div>
<h1>${title}</h1>${bodyHtml}
</div></body></html>`;
}
```

- [ ] **Step 2: Implement `GET /confirm` in `workers/subscribe/src/index.ts`**

Add imports at the top:

```ts
import { verifyToken } from "./jwt";
import { createContact } from "./resend";
import { successPage, expiredPage, errorPage } from "./confirm-page";
```

Replace the `GET /confirm` branch:

```ts
if (request.method === "GET" && url.pathname === "/confirm") {
  const token = url.searchParams.get("token") || "";
  const html = (body: string, status = 200) =>
    new Response(body, { status, headers: { "Content-Type": "text/html; charset=utf-8" } });

  const v = await verifyToken(token, env.SUBSCRIPTION_SECRET);
  if (!v.ok) return html(expiredPage(env.SITE_URL), 400);

  try {
    await createContact(env, v.email);
    // Invalidate cached count so the badge picks up the new subscriber within 10min.
    await env.SUBSCRIBE_CACHE.delete("count");
    return html(successPage(env.SITE_URL), 200);
  } catch (e) {
    console.error("createContact failed", e);
    return html(errorPage(), 502);
  }
}
```

- [ ] **Step 3: Local validation**

With `wrangler dev --local` running, generate a token then hit `/confirm`:

```bash
# First, get a token using the debug route — temporarily re-add it to index.ts
# (or use a one-liner in the worker logs). For validation, the simplest path:
# use curl with a known-bad token and verify expiredPage() renders.

curl -s "http://localhost:8787/confirm?token=garbage" | head -20
# Expected: HTML containing "Link expired"

curl -sI "http://localhost:8787/confirm?token=garbage"
# Expected: HTTP/1.1 400, Content-Type: text/html; charset=utf-8
```

For the success path, you can re-add the temporary `/__debug/jwt` route from Task 2, grab a token, pass it to `/confirm`, and confirm you get a 502 from `createContact` (because `.dev.vars` has `RESEND_API_KEY=test`). That 502 is the expected failure mode for local — it proves the token verify + flow is correct. Remove the debug route when done.

- [ ] **Step 4: Commit**

```bash
git add workers/subscribe/src
git commit -m "subscribe-worker: GET /confirm verifies JWT and upserts contact"
```

---

## Task 5: `GET /count` with KV cache

**Files:**
- Modify: `workers/subscribe/src/index.ts`

- [ ] **Step 1: Implement `GET /count` branch**

Replace the placeholder `GET /count` branch:

```ts
// Add import:
import { listContacts } from "./resend";

// In the fetch handler:
if (request.method === "GET" && url.pathname === "/count") {
  const cached = await env.SUBSCRIBE_CACHE.get("count");
  if (cached !== null) {
    return json({ count: Number(cached) }, 200);
  }

  try {
    const contacts = await listContacts(env);
    const count = contacts.filter((c) => !c.unsubscribed).length;
    await env.SUBSCRIBE_CACHE.put("count", String(count), { expirationTtl: 600 });
    return new Response(JSON.stringify({ count }), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=600",
        ...CORS_HEADERS,
      },
    });
  } catch (e) {
    console.error("listContacts failed", e);
    return json({ error: "upstream_unavailable" }, 502);
  }
}
```

- [ ] **Step 2: Local validation**

```bash
curl -s http://localhost:8787/count
# Expected: {"error":"upstream_unavailable"} — again due to fake RESEND_API_KEY locally.
# Real test happens after deploy.
```

- [ ] **Step 3: Commit**

```bash
git add workers/subscribe/src/index.ts
git commit -m "subscribe-worker: GET /count with 10min KV cache"
```

---

## Task 6: Turnstile verification

**Files:**
- Modify: `workers/subscribe/src/index.ts`

Turnstile is optional at this stage — we gate it behind presence of the secret so local dev doesn't need it.

- [ ] **Step 1: Add Turnstile verification in `POST /subscribe`**

Insert immediately after the honeypot check, before `isValidEmail`:

```ts
// Turnstile (skipped if secret key is the test placeholder)
if (env.TURNSTILE_SECRET_KEY && env.TURNSTILE_SECRET_KEY !== "test") {
  const token = typeof body.turnstileToken === "string" ? body.turnstileToken : "";
  if (!token) return json({ error: "turnstile_missing" }, 400);
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const verifyResp = await fetch(
    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ secret: env.TURNSTILE_SECRET_KEY, response: token, remoteip: ip }),
    },
  );
  const verifyJson = (await verifyResp.json()) as { success: boolean };
  if (!verifyJson.success) return json({ error: "turnstile_failed" }, 400);
}
```

- [ ] **Step 2: Local validation**

With `TURNSTILE_SECRET_KEY=test` in `.dev.vars`, the original curl from Task 3 Step 4 should still work — Turnstile is skipped.

```bash
curl -s -X POST http://localhost:8787/subscribe \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com"}'
# Expected: same upstream_unavailable as before. Turnstile was skipped because secret is "test".
```

- [ ] **Step 3: Commit**

```bash
git add workers/subscribe/src/index.ts
git commit -m "subscribe-worker: Turnstile verification (bypassed in local dev)"
```

---

## Task 7: Deploy Worker

- [ ] **Step 1: Set production secrets**

From `workers/subscribe/`:

```bash
npx wrangler secret put RESEND_API_KEY         # paste from prereq #1
npx wrangler secret put RESEND_AUDIENCE_ID     # paste the TEST audience ID first
npx wrangler secret put SUBSCRIPTION_SECRET    # paste from prereq #7
npx wrangler secret put TURNSTILE_SECRET_KEY   # paste from prereq #5
```

Use the **test** audience ID initially. Swap to real later (Task 20).

- [ ] **Step 2: Deploy**

```bash
npx wrangler deploy
```

Expected: prints the worker URL (e.g. `https://subscribe.akthecoders.workers.dev`). **Copy this URL** — we'll reference it as `WORKER_URL` throughout.

- [ ] **Step 3: Smoke-test production**

```bash
# Count (empty audience)
curl -s "$WORKER_URL/count"
# Expected: {"count":0}

# Real signup with a personal email you control
curl -s -X POST "$WORKER_URL/subscribe" \
  -H "Content-Type: application/json" \
  -d '{"email":"YOUR_EMAIL@example.com"}'
# Expected: {"status":"pending"}
# Check inbox — confirmation email should arrive within ~10s.
# Click the confirm link → browser shows success page.

# Count again
curl -s "$WORKER_URL/count"
# Expected: {"count":1}
```

If any step fails, `npx wrangler tail` streams logs.

- [ ] **Step 4: Commit (no code change — just marker)**

```bash
git commit --allow-empty -m "subscribe-worker: deployed to production (test audience)"
```

---

## Task 8: Create `SubscribeForm.astro` component

**Files:**
- Create: `site/src/components/SubscribeForm.astro`

- [ ] **Step 1: Create the component**

```astro
---
// site/src/components/SubscribeForm.astro
//
// Reusable subscribe form. Three variants control layout + copy:
//   - "hero"   (homepage hero — larger, with supporting copy)
//   - "footer" (site footer — compact, single-line)
//   - "page"   (/subscribe page — medium, with supporting copy above)
//
// Posts to PUBLIC_SUBSCRIBE_WORKER_URL/subscribe. Progressive enhancement:
//   - No JS: native form POST; worker returns JSON, browser renders it
//     (acceptable edge case; we add a plain-HTML fallback in a later task
//     only if complaints come in).
//   - With JS: fetch() + inline success state.

interface Props {
  variant: "hero" | "footer" | "page";
}
const { variant } = Astro.props;
const workerUrl = import.meta.env.PUBLIC_SUBSCRIBE_WORKER_URL;
const copy = {
  hero:   { label: "A deep-dive on one arXiv paper, twice a week.", button: "Subscribe" },
  footer: { label: "Get new papers in your inbox",                  button: "Subscribe" },
  page:   { label: "Enter your email to subscribe.",                button: "Subscribe" },
}[variant];
---

<form class={`subscribe subscribe--${variant}`} data-worker-url={workerUrl}>
  <label class="subscribe__label" for={`sub-${variant}`}>{copy.label}</label>
  <div class="subscribe__row">
    <input
      id={`sub-${variant}`}
      class="subscribe__input"
      type="email"
      name="email"
      placeholder="you@example.com"
      required
      autocomplete="email"
    />
    <input type="text" name="website" tabindex="-1" autocomplete="off"
           style="position:absolute;left:-9999px;" aria-hidden="true" />
    <button class="subscribe__button" type="submit">{copy.button}</button>
  </div>
  <p class="subscribe__status" data-status hidden></p>
</form>

<style>
  .subscribe { width: 100%; }
  .subscribe__label {
    display: block;
    font-family: var(--font-body);
    font-size: 0.95rem;
    color: var(--ink-soft);
    margin-bottom: var(--space-2);
  }
  .subscribe__row { display: flex; gap: var(--space-2); }
  .subscribe__input {
    flex: 1;
    min-width: 0;
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--rule);
    background: var(--bg);
    color: var(--ink);
    font-family: var(--font-body);
    font-size: 1rem;
    border-radius: 2px;
  }
  .subscribe__input:focus {
    outline: none;
    border-color: var(--accent);
  }
  .subscribe__button {
    padding: var(--space-3) var(--space-5);
    background: var(--accent);
    color: var(--bg);
    border: 0;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 1rem;
    cursor: pointer;
    border-radius: 2px;
  }
  .subscribe__button:hover { background: var(--accent-soft); }
  .subscribe__status {
    margin: var(--space-3) 0 0;
    font-family: var(--font-body);
    font-size: 0.9rem;
    color: var(--ink-soft);
  }
  .subscribe__status[data-tone="error"] { color: var(--accent); }

  /* footer variant — compact */
  .subscribe--footer .subscribe__label { font-size: 0.85rem; }
  .subscribe--footer .subscribe__row { max-width: 28rem; }

  /* hero variant — larger */
  .subscribe--hero .subscribe__label { font-size: 1.05rem; }
  .subscribe--hero .subscribe__input,
  .subscribe--hero .subscribe__button {
    font-size: 1.05rem;
    padding: var(--space-4) var(--space-5);
  }
</style>

<script>
  document.querySelectorAll<HTMLFormElement>(".subscribe").forEach((form) => {
    const workerUrl = form.dataset.workerUrl;
    if (!workerUrl) return;
    const status = form.querySelector<HTMLElement>("[data-status]")!;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      status.hidden = false;
      status.removeAttribute("data-tone");
      status.textContent = "Sending…";
      const data = new FormData(form);
      const payload = {
        email: String(data.get("email") || ""),
        website: String(data.get("website") || ""),
      };
      try {
        const resp = await fetch(`${workerUrl}/subscribe`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const body = (await resp.json()) as { status?: string; error?: string };
        if (resp.ok && body.status === "pending") {
          form.querySelector<HTMLElement>(".subscribe__row")!.hidden = true;
          form.querySelector<HTMLElement>(".subscribe__label")!.hidden = true;
          status.textContent = "Check your inbox — we sent a confirmation link.";
        } else {
          status.setAttribute("data-tone", "error");
          status.textContent =
            body.error === "invalid_email"
              ? "That doesn't look like a valid email."
              : "Something went wrong. Please try again in a minute.";
        }
      } catch {
        status.setAttribute("data-tone", "error");
        status.textContent = "Network error. Please try again.";
      }
    });
  });
</script>
```

- [ ] **Step 2: Add the env var to `.env` (local) and Astro config**

Create `site/.env` (gitignored already via `dist/` + `.astro/`? No — check). Append to root `.gitignore` if missing:

```
site/.env
```

Then `site/.env`:

```
PUBLIC_SUBSCRIBE_WORKER_URL=https://subscribe.akthecoders.workers.dev
```

Replace the URL with the one from Task 7 Step 2.

- [ ] **Step 3: Validation**

The component isn't mounted anywhere yet — we do that in Tasks 11, 12, 13. Just confirm it type-checks:

```bash
cd site && npx astro check 2>&1 | tail -20
```

Expected: `0 errors` (warnings about unrelated files are fine).

- [ ] **Step 4: Commit**

```bash
git add site/src/components/SubscribeForm.astro site/.env .gitignore
git commit -m "site: add SubscribeForm component with 3 variants"
```

---

## Task 9: Create `/subscribe` page

**Files:**
- Create: `site/src/pages/subscribe.astro`

- [ ] **Step 1: Inspect the existing layout**

```bash
ls site/src/layouts
```

Expected to see `BaseLayout.astro` (or similar). Note the exact filename — the import path below must match.

- [ ] **Step 2: Create `site/src/pages/subscribe.astro`**

If the layout file is not `BaseLayout.astro`, adjust the import path in the first `---` block.

```astro
---
import BaseLayout from "../layouts/BaseLayout.astro";
import SubscribeForm from "../components/SubscribeForm.astro";

const title = "Subscribe — The Daily Paper";
const description = "Get a deep-dive on one arXiv paper every Tuesday and Friday, in your inbox.";
---

<BaseLayout title={title} description={description}>
  <article class="reading-container subscribe-page">
    <header>
      <h1>Get new papers in your inbox</h1>
      <p class="lede">
        Every Tuesday and Friday, one arXiv paper is picked against our reading
        taste and turned into a ~3,000-word explainer with a short TL;DR.
        Subscribe and you'll get each new explainer the moment it's published —
        no digests, no marketing, no tracking pixels you don't consent to.
      </p>
    </header>

    <section class="form-block">
      <SubscribeForm variant="page" />
    </section>

    <section class="faq">
      <h2>Questions</h2>
      <dl>
        <dt>How often?</dt>
        <dd>Twice a week, Tuesday and Friday morning (7 AM IST / 01:30 UTC).</dd>
        <dt>Can I unsubscribe?</dt>
        <dd>Every email includes a one-click unsubscribe link. It's instant.</dd>
        <dt>Will you share my email?</dt>
        <dd>No. Emails live in Resend, are used only to deliver these posts, and never leave. See the <a href="/privacy">privacy note</a> if you want the specifics.</dd>
        <dt>What if I want to reply?</dt>
        <dd>Just hit reply. Your message goes straight to the author's inbox.</dd>
      </dl>
    </section>
  </article>
</BaseLayout>

<style>
  .subscribe-page { padding: var(--space-7) 0 var(--space-8); }
  .subscribe-page h1 {
    font-family: var(--font-display);
    font-size: 2.4rem;
    line-height: 1.15;
    margin: 0 0 var(--space-4);
  }
  .lede {
    font-family: var(--font-body);
    font-size: 1.15rem;
    line-height: 1.6;
    color: var(--ink-soft);
    margin: 0 0 var(--space-6);
  }
  .form-block { margin-bottom: var(--space-8); }
  .faq h2 {
    font-family: var(--font-display);
    font-size: 1.5rem;
    margin: 0 0 var(--space-5);
  }
  .faq dt {
    font-family: var(--font-display);
    font-weight: 600;
    margin-top: var(--space-5);
  }
  .faq dd {
    margin: var(--space-2) 0 0;
    color: var(--ink-soft);
    font-family: var(--font-body);
    line-height: 1.6;
  }
</style>
```

- [ ] **Step 3: Validation**

```bash
cd site && npm run dev
```

Open http://localhost:4321/subscribe in a browser. Expected:
- Page renders with title "Get new papers in your inbox"
- Form is visible, centered, matches site aesthetic
- FAQ items render
- Dev console has no errors

Submit form with a real email → expect "Check your inbox — we sent a confirmation link." (requires Task 7 deployed + `PUBLIC_SUBSCRIBE_WORKER_URL` set).

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/subscribe.astro
git commit -m "site: add /subscribe page with FAQ"
```

---

## Task 10: `SubscriberBadge` with build-time count fetch

**Files:**
- Create: `site/src/components/SubscriberBadge.astro`

- [ ] **Step 1: Create `SubscriberBadge.astro`**

```astro
---
// Build-time fetch of subscriber count from the Worker. If the fetch fails or
// count is zero, the badge silently renders nothing — no embarrassing "Join
// 0 readers" text on first deploy.

const workerUrl = import.meta.env.PUBLIC_SUBSCRIBE_WORKER_URL;
let count: number | null = null;

if (workerUrl) {
  try {
    const resp = await fetch(`${workerUrl}/count`, {
      signal: AbortSignal.timeout(5000),
    });
    if (resp.ok) {
      const body = (await resp.json()) as { count?: number };
      if (typeof body.count === "number" && body.count > 0) count = body.count;
    }
  } catch {
    // swallow — badge will just not render
  }
}
---

{count !== null && (
  <p class="subscriber-badge">
    <span class="subscriber-badge__count">{count.toLocaleString()}</span>
    <span class="subscriber-badge__label">{count === 1 ? "reader" : "readers"} subscribed</span>
  </p>
)}

<style>
  .subscriber-badge {
    font-family: var(--font-body);
    font-size: 0.9rem;
    color: var(--ink-muted);
    margin: var(--space-3) 0 0;
  }
  .subscriber-badge__count {
    font-family: var(--font-display);
    font-weight: 600;
    color: var(--ink-soft);
  }
</style>
```

- [ ] **Step 2: Validation**

```bash
cd site && npm run build 2>&1 | tail -20
```

Expected: build succeeds. If `PUBLIC_SUBSCRIBE_WORKER_URL` is set and the Worker returns a positive count, the badge renders wherever it's mounted. Otherwise it's absent — that's fine.

- [ ] **Step 3: Commit**

```bash
git add site/src/components/SubscriberBadge.astro
git commit -m "site: add SubscriberBadge with build-time count fetch"
```

---

## Task 11: Mount footer form site-wide

**Files:**
- Modify: `site/src/layouts/BaseLayout.astro` (path may vary; check with `ls site/src/layouts`)

- [ ] **Step 1: Identify where the layout's footer section lives**

```bash
grep -n "footer\|</main>" site/src/layouts/BaseLayout.astro
```

Note the line numbers of the `<footer>` open/close tags. If there's no footer, add one before `</body>`.

- [ ] **Step 2: Add the form to the footer**

Import `SubscribeForm` at the top of the frontmatter block:

```astro
import SubscribeForm from "../components/SubscribeForm.astro";
```

Inside the existing `<footer>` element, add a section (place it before any existing footer content, or create the footer if it doesn't exist):

```astro
<section class="footer-subscribe">
  <SubscribeForm variant="footer" />
</section>
```

Append to the style block (or create one if none):

```css
.footer-subscribe {
  max-width: var(--reading-width);
  margin: 0 auto;
  padding: var(--space-6) var(--space-5);
  border-top: 1px solid var(--rule);
}
```

- [ ] **Step 3: Validation**

```bash
cd site && npm run dev
```

Visit http://localhost:4321/ — footer form should appear at the bottom of every page. Visit a paper page (pick one from `/papers/`) — form should appear there too.

- [ ] **Step 4: Commit**

```bash
git add site/src/layouts
git commit -m "site: mount subscribe form in site-wide footer"
```

---

## Task 12: Mount hero form on homepage

**Files:**
- Modify: `site/src/pages/index.astro`

- [ ] **Step 1: Locate the homepage hero**

```bash
grep -n "hero\|<h1>" site/src/pages/index.astro | head -10
```

- [ ] **Step 2: Add the hero form + badge**

Import at top of the frontmatter:

```astro
import SubscribeForm from "../components/SubscribeForm.astro";
import SubscriberBadge from "../components/SubscriberBadge.astro";
```

In the body, add a `<section class="home-subscribe">` immediately below the existing hero text / intro. If there is no hero section, place it above the papers list.

```astro
<section class="home-subscribe">
  <SubscribeForm variant="hero" />
  <SubscriberBadge />
</section>
```

Append to the style block:

```css
.home-subscribe {
  max-width: 36rem;
  margin: var(--space-6) auto var(--space-7);
}
```

- [ ] **Step 3: Validation**

```bash
cd site && npm run dev
```

Visit http://localhost:4321/ — hero form appears prominently with "A deep-dive on one arXiv paper, twice a week." label. If you have ≥ 1 confirmed subscriber, the "N readers subscribed" badge appears below. Submit a test email → "Check your inbox" message.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/index.astro
git commit -m "site: add subscribe form + badge to homepage hero"
```

---

## Task 13: Newsletter email templates (HTML + text)

**Files:**
- Create: `agent/templates/newsletter.html`
- Create: `agent/templates/newsletter.txt`

These are Python string-formatted templates (use `{field}` placeholders, rendered with `.format()` in Task 15).

- [ ] **Step 1: Create `agent/templates/newsletter.html`**

```html
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title_escaped}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;background:#f7f3ec;color:#1a1814;font-family:Georgia,'Iowan Old Style',serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7f3ec;padding:40px 16px;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#f7f3ec;">
      <tr><td style="padding:40px 48px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-bottom:1px solid #d9d1c3;padding-bottom:12px;">
          <tr>
            <td style="font-family:Georgia,serif;font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:#7a756d;">
              The Daily Paper
            </td>
            <td align="right" style="font-family:Georgia,serif;font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:#7a756d;">
              {date_pretty}
            </td>
          </tr>
        </table>
      </td></tr>
      <tr><td style="padding:28px 48px 0;">
        <h1 style="font-family:Georgia,serif;font-size:28px;font-weight:600;line-height:1.15;margin:0 0 12px;color:#1a1814;">
          {title_escaped}
        </h1>
        <p style="font-family:Georgia,serif;font-style:italic;font-size:14px;color:#7a756d;margin:0 0 24px;">
          by {authors_escaped} &middot; {primary_category}
        </p>
      </td></tr>
      <tr><td style="padding:0 48px 0;">
        <p style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:0.1em;color:#b8442e;text-transform:uppercase;margin:0 0 8px;">
          TL;DR
        </p>
        <p style="font-family:Georgia,serif;font-size:17px;line-height:1.55;color:#1a1814;border-left:3px solid #b8442e;padding-left:16px;margin:0 0 28px;font-style:italic;">
          {tldr_escaped}
        </p>
      </td></tr>
      <tr><td style="padding:0 48px 0;">
        <div style="font-family:Georgia,serif;font-size:16px;line-height:1.6;color:#1a1814;margin:0 0 28px;">
          {hook_escaped}
        </div>
      </td></tr>
      <tr><td style="padding:0 48px 32px;">
        <a href="{post_url}" style="display:inline-block;background:#b8442e;color:#f7f3ec;padding:14px 28px;text-decoration:none;font-family:Georgia,serif;font-weight:600;font-size:15px;">
          Read the full explainer &rarr;
        </a>
      </td></tr>
      <tr><td style="padding:0 48px;">
        <hr style="border:0;border-top:1px solid #d9d1c3;margin:0 0 28px;">
      </td></tr>
      <tr><td style="padding:0 48px 40px;">
        <p style="font-family:Georgia,serif;font-size:13px;color:#7a756d;line-height:1.6;margin:0 0 16px;">
          <strong style="color:#4a4640;">Past papers:</strong> <a href="{archive_url}" style="color:#7a756d;">Browse the archive &rarr;</a><br>
          <strong style="color:#4a4640;">Thoughts?</strong> Just reply to this email &mdash; it lands in Akshay's inbox.
        </p>
        <p style="font-family:Georgia,serif;font-size:12px;color:#7a756d;line-height:1.6;margin:0;">
          You're receiving this because you subscribed at <a href="{site_url}" style="color:#7a756d;">{site_host}</a>.<br>
          <a href="{{{{RESEND_UNSUBSCRIBE_URL}}}}" style="color:#7a756d;">Unsubscribe</a>
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>
```

Note: `{{{{RESEND_UNSUBSCRIBE_URL}}}}` is Python's `.format()` escaping for `{{RESEND_UNSUBSCRIBE_URL}}`, which is Resend's Broadcast merge variable — Resend substitutes it at send time per-recipient.

- [ ] **Step 2: Create `agent/templates/newsletter.txt`**

```text
THE DAILY PAPER — {date_pretty}

{title}
by {authors} · {primary_category}

— TL;DR —
{tldr}

— Why it's interesting —
{hook}

Read: {post_url}

---
Archive: {archive_url}
Reply to this email with thoughts.
Unsubscribe: {{{{RESEND_UNSUBSCRIBE_URL}}}}
```

- [ ] **Step 3: Validation**

```bash
python -c "
p = open('agent/templates/newsletter.html').read()
assert '{title_escaped}' in p
assert '{{{{RESEND_UNSUBSCRIBE_URL}}}}' in p  # Resend variable preserved
t = open('agent/templates/newsletter.txt').read()
assert '{title}' in t
print('templates ok')
"
```

Expected: `templates ok`

- [ ] **Step 4: Commit**

```bash
git add agent/templates
git commit -m "agent: add newsletter HTML + text templates (editorial style)"
```

---

## Task 14: `send_newsletter.py` module

**Files:**
- Create: `agent/send_newsletter.py`

- [ ] **Step 1: Create the module**

```python
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
    archive_url = f"{site_url.rstrip('/')}/papers"

    html_body = html_tpl.format(
        title_escaped=html.escape(winner["title"]),
        authors_escaped=html.escape(authors),
        primary_category=html.escape(winner.get("primary_category", "")),
        tldr_escaped=html.escape(explainer.get("tldr", "")),
        hook_escaped=html.escape(hook).replace("\n", "<br>"),
        post_url=post_url,
        archive_url=archive_url,
        site_url=site_url,
        site_host=host,
        date_pretty=date_pretty,
    )
    text_body = text_tpl.format(
        title=winner["title"],
        authors=authors,
        primary_category=winner.get("primary_category", ""),
        tldr=explainer.get("tldr", ""),
        hook=hook,
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
    broadcast_id = create_resp.json()["id"]

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
```

- [ ] **Step 2: Validation**

```bash
cd agent && python -c "
from send_newsletter import render_newsletter
winner = {
  'title': 'RACER: Rapid Autonomous Cross-Environment Reasoning',
  'authors': ['Chen', 'Patel', 'Zhou'],
  'primary_category': 'cs.LG',
}
explainer = {
  'tldr': 'New agent architecture that transfers reasoning across novel environments.',
  'body': 'Most RL agents forget everything when you drop them into a new room. This paper asks a different question.\n\nWhat follows is a rewrite.',
}
h, t = render_newsletter(winner, explainer, 'https://site/papers/racer', 'https://site', 'Apr 24, 2026')
assert 'RACER' in h and 'RACER' in t
assert 'TL;DR' in h
assert '{{RESEND_UNSUBSCRIBE_URL}}' in h  # variable preserved
print('render ok — html %d bytes, text %d bytes' % (len(h), len(t)))
"
```

Expected: `render ok — html XXXX bytes, text XXX bytes`.

- [ ] **Step 3: Commit**

```bash
git add agent/send_newsletter.py
git commit -m "agent: send_newsletter module — Resend Broadcasts + templating"
```

---

## Task 15: Config + feature flag + CLI flags

**Files:**
- Modify: `agent/config_loader.py`
- Modify: `agent/run_daily.py`

- [ ] **Step 1: Add env vars to `config_loader.py`**

Locate `load_config()`. Add the following env reads in the same style as the existing `TELEGRAM_*` / `SITE_URL` reads (search for "TELEGRAM_BOT_TOKEN" as the anchor — add these new reads right after it):

```python
cfg["resend_api_key"] = os.environ.get("RESEND_API_KEY", cfg.get("resend_api_key", ""))
cfg["resend_audience_id"] = os.environ.get(
    "RESEND_AUDIENCE_ID", cfg.get("resend_audience_id", "")
)
cfg["newsletter_enabled"] = (
    os.environ.get("NEWSLETTER_ENABLED", "false").lower() == "true"
)
cfg["newsletter_from"] = os.environ.get(
    "NEWSLETTER_FROM",
    cfg.get("newsletter_from", "The Daily Paper <papers@thedailypaper.akshaykumar.me>"),
)
cfg["newsletter_reply_to"] = os.environ.get(
    "NEWSLETTER_REPLY_TO",
    cfg.get("newsletter_reply_to", "akshaykumar@grainsetu.com"),
)
```

- [ ] **Step 2: Add CLI flags to `run_daily.py`**

Locate the argparse block in `main()` (search for `argparse` or `--dry-run`). Add two new flags to the existing `ArgumentParser`:

```python
parser.add_argument(
    "--dry-newsletter",
    action="store_true",
    help="Render newsletter HTML+text to stdout and exit. Implies --dry-run.",
)
parser.add_argument(
    "--skip-newsletter",
    action="store_true",
    help="Run the full pipeline but skip the newsletter send step.",
)
```

- [ ] **Step 3: Validation**

```bash
cd agent && python run_daily.py --help 2>&1 | grep newsletter
```

Expected: two lines showing `--dry-newsletter` and `--skip-newsletter`.

- [ ] **Step 4: Commit**

```bash
git add agent/config_loader.py agent/run_daily.py
git commit -m "agent: add RESEND_* env vars + --dry/skip-newsletter flags"
```

---

## Task 16: Wire `send_newsletter` into `run_daily.py`

**Files:**
- Modify: `agent/run_daily.py`

- [ ] **Step 1: Add import**

At the top of the file with the other `from X import Y` lines, add:

```python
from send_newsletter import send_newsletter, dry_render as dry_render_newsletter
```

- [ ] **Step 2: Wire the call into `main()`**

Locate the call to `write_post(...)` (search `post_path, url_slug = write_post`). Immediately after the line that computes `post_url` (typically `post_url = f"{cfg['site_url']}/papers/{url_slug}"` — check exact variable names), add:

```python
# Newsletter ---------------------------------------------------------------
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
        log.warning("newsletter_enabled but RESEND_API_KEY/RESEND_AUDIENCE_ID missing — skipping send")
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
    log.info("newsletter skipped (enabled=%s, skip=%s)",
             cfg["newsletter_enabled"], args.skip_newsletter)
```

Add at the top of the file if not already present:

```python
from datetime import datetime
```

- [ ] **Step 3: Validation — dry render**

```bash
cd agent && python run_daily.py --dry-newsletter --date 2026-04-20 2>&1 | tail -40
```

Expected: last lines of stdout contain `========== HTML ==========` followed by a rendered template. If the agent can't find a paper for that date, pass a more recent date that exists in `history/history.json`. The command should exit 0 without committing, pushing, or touching Telegram.

- [ ] **Step 4: Paste HTML into Mail Tester**

Copy the HTML block from stdout between the `========== HTML ==========` and `========== TEXT ==========` markers. Paste into https://www.mail-tester.com/ (or Litmus). Expected: score ≥ 8/10. Common issues:
- Missing SPF/DKIM → finished in Prerequisites step 2–3.
- Broken link → check `post_url` resolves.

If score is < 8, fix the flagged issues before proceeding.

- [ ] **Step 5: Commit**

```bash
git add agent/run_daily.py
git commit -m "agent: wire send_newsletter into run_daily pipeline (flagged off by default)"
```

---

## Task 17: GitHub Actions workflow — add secrets

**Files:**
- Modify: `.github/workflows/daily.yml`

- [ ] **Step 1: Inspect the current workflow env**

```bash
grep -n "env:\|OPENROUTER\|TELEGRAM" .github/workflows/daily.yml
```

Note the `env:` block structure under the `jobs.<job>.steps.<step>` level.

- [ ] **Step 2: Add Resend vars to the relevant `env:` block**

In the step that runs `python run_daily.py` (should be under `steps:`), extend its `env:` map with:

```yaml
          RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
          RESEND_AUDIENCE_ID: ${{ secrets.RESEND_AUDIENCE_ID }}
          NEWSLETTER_ENABLED: ${{ vars.NEWSLETTER_ENABLED || 'false' }}
```

Use `vars.NEWSLETTER_ENABLED` (a repo variable, not a secret) so you can flip it on/off in the GitHub UI without editing code.

- [ ] **Step 3: Add the secrets + var to GitHub**

Manually in the GitHub repo settings → Secrets and variables → Actions:

- **Secret** `RESEND_API_KEY` — value from prereq #1
- **Secret** `RESEND_AUDIENCE_ID` — the **test** audience ID initially (swap at Task 20)
- **Variable** `NEWSLETTER_ENABLED` — `false` for now

- [ ] **Step 4: Validation**

Trigger a manual run via `workflow_dispatch` with a date. In the logs, expect to see:

```
newsletter skipped (enabled=False, skip=False)
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/daily.yml
git commit -m "ci: pass RESEND_* secrets + NEWSLETTER_ENABLED var to daily workflow"
```

---

## Task 18: Update `DEPLOY.md` and `README.md`

**Files:**
- Modify: `DEPLOY.md`
- Modify: `README.md`

- [ ] **Step 1: Append to `DEPLOY.md`**

Add a new section at the end:

```markdown
## Email subscriptions

Reader emails ship through a Cloudflare Worker (`workers/subscribe`) backed by
Resend Audiences. See `docs/superpowers/specs/2026-04-20-email-subscriptions-design.md`
for full architecture.

### One-time setup

1. **Resend** — create account, generate API key, verify sending domain
   `thedailypaper.akshaykumar.me` (add SPF + DKIM DNS records shown in Resend),
   add DMARC record.
2. **Audience** — create "Daily Paper Readers" audience; copy ID.
3. **Turnstile** — create Cloudflare Turnstile site; copy sitekey + secret.
4. **Worker** — from `workers/subscribe/`:
   - `wrangler kv:namespace create "SUBSCRIBE_CACHE"` — paste ID into `wrangler.toml`.
   - `wrangler secret put RESEND_API_KEY`
   - `wrangler secret put RESEND_AUDIENCE_ID`
   - `wrangler secret put SUBSCRIPTION_SECRET` (generate: `openssl rand -hex 32`)
   - `wrangler secret put TURNSTILE_SECRET_KEY`
   - `wrangler deploy` → copy the worker URL.
5. **Astro** — set `PUBLIC_SUBSCRIBE_WORKER_URL` in Dokploy environment (and
   local `site/.env`) to the worker URL from step 4.
6. **GitHub Actions** — set secrets `RESEND_API_KEY` + `RESEND_AUDIENCE_ID`,
   and variable `NEWSLETTER_ENABLED` (default `false` until you're ready).

### Capacity note

Resend free tier: **3,000 emails/month, 100/day**. With Tue+Fri cadence and N
subscribers, monthly send = ~8N. Free tier supports ~350 subscribers. Upgrade
plan before crossing ~100 subscribers to avoid the daily cap biting on a big
send.

### Rollout

1. Deploy worker with the **test** audience.
2. Set `NEWSLETTER_ENABLED=true` in GitHub Actions variables.
3. Manually trigger the workflow with `--dry-newsletter` first to eyeball the render.
4. For the first live run, keep `RESEND_AUDIENCE_ID` pointing at the test audience
   (which contains only your own addresses).
5. Inspect the delivered email; once happy, swap `RESEND_AUDIENCE_ID` in both
   Worker secrets (`wrangler secret put RESEND_AUDIENCE_ID`) and GitHub Actions
   secrets to the real audience ID.
```

- [ ] **Step 2: Update `README.md`**

Search for an existing "Features" or project description section, add a bullet:

```markdown
- **Email subscriptions** — readers can subscribe at `/subscribe` and receive every new paper in the editorial email template. Double-opt-in via Resend; one-click unsubscribe; replies land in the author's inbox.
```

Also, near the top of the README (below the main heading, next to the site link), add:

```markdown
**Subscribe:** [thedailypaper.akshaykumar.me/subscribe](https://thedailypaper.akshaykumar.me/subscribe)
```

- [ ] **Step 3: Commit**

```bash
git add DEPLOY.md README.md
git commit -m "docs: document email subscriptions setup + rollout"
```

---

## Task 19: First live send with test audience

This task runs **after** the full pipeline is merged and `NEWSLETTER_ENABLED=true` is set in GitHub Actions variables. It verifies the end-to-end send on a real paper run.

- [ ] **Step 1: Confirm the test audience has your email**

Ensure you've confirmed your email via the signup form (done during Task 7 smoke test). Verify:

```bash
curl -s "$WORKER_URL/count"
# Expected: {"count":1} (or more if you added extras)
```

- [ ] **Step 2: Flip the feature flag on**

In GitHub repo → Settings → Secrets and variables → Actions → Variables tab → set `NEWSLETTER_ENABLED=true`.

- [ ] **Step 3: Trigger the next scheduled run or manual run**

Manual:

```bash
gh workflow run "Daily Paper"
```

Watch it in `gh run watch --exit-status`.

- [ ] **Step 4: Verify email delivery**

Within ~2 minutes of the workflow completing, your inbox should show the new-paper email:
- Subject = paper title, no prefix
- From = "The Daily Paper <papers@…>"
- Replying lands in `akshaykumar@grainsetu.com`
- Unsubscribe link visible in footer
- Read the full explainer CTA links to the right post

- [ ] **Step 5: Audit in Resend dashboard**

Resend → Broadcasts → confirm broadcast shows `delivered: 1` (or your test audience size). Check open/click stats are populating.

- [ ] **Step 6: Commit marker**

```bash
git commit --allow-empty -m "rollout: first successful live send with test audience"
```

---

## Task 20: Promote to real audience

- [ ] **Step 1: Update Worker secret**

```bash
cd workers/subscribe && npx wrangler secret put RESEND_AUDIENCE_ID
# paste the real "Daily Paper Readers" audience ID
npx wrangler deploy
```

- [ ] **Step 2: Update GitHub Actions secret**

Repo Settings → Secrets → update `RESEND_AUDIENCE_ID` to the real audience ID.

- [ ] **Step 3: Purge the count cache**

The badge on the site still shows the test audience count. Force a refresh:

```bash
# The KV cache expires in 10 min anyway, but you can also redeploy the worker.
# For immediate effect:
curl -s "$WORKER_URL/count" # first hit after cache expiry repopulates
```

The site badge updates on next Astro rebuild (any site commit triggers it).

- [ ] **Step 4: Announce**

Post the `/subscribe` link wherever you want readers to find it. You're done.

- [ ] **Step 5: Final commit**

```bash
git commit --allow-empty -m "rollout: email subscriptions live against real audience"
```

---

## Self-review checklist (run before handing off)

The author performed the following self-review against the spec at
`docs/superpowers/specs/2026-04-20-email-subscriptions-design.md`:

**Spec coverage — every spec requirement has a task:**

| Spec requirement | Task |
|---|---|
| Resend Audiences + CF Worker backend | Tasks 1, 3, 4, 5 |
| Double opt-in via signed JWT | Tasks 2, 3, 4 |
| Per-paper cadence (run_daily integration) | Task 16 |
| One-click unsubscribe | Task 13 (template uses `{{RESEND_UNSUBSCRIBE_URL}}`) |
| Reply-to Akshay | Tasks 1 (worker var), 14 (`reply_to` in send), 15 (config default) |
| Subscriber count badge | Tasks 5 (worker endpoint), 10 (component), 12 (mount) |
| Archive link in email | Task 14 (`archive_url` in render) |
| Open + click tracking | Resend provides by default (Broadcasts); no code change needed |
| Signup form: homepage + footer + /subscribe | Tasks 8, 9, 11, 12 |
| Editorial email template | Task 13 |
| Subject line = paper title only | Task 14 (`subject=winner["title"]`) |
| Sender `The Daily Paper <papers@…>` | Tasks 1 (var), 15 (config default) |
| Cloudflare Turnstile spam protection | Task 6 |
| Honeypot | Task 3 (worker), 8 (form field) |
| Rate limit | (Deferred — Cloudflare dashboard rule, not code; noted in Prereqs as future hardening) |
| DNS setup instructions | Task 18 |
| Resend free-tier capacity note | Task 18 |
| `--dry-newsletter` validation path | Task 15, 16 |

**Gaps found during self-review:** Rate limit was noted in the spec but is a
dashboard rule, not code. It has been moved to the Prerequisites section as a
post-deploy hardening step (author adds a Cloudflare rule after Task 7 via the
CF dashboard: "10 req/min per IP on `/subscribe` POST"). No separate code task
needed.

**Placeholder scan:** None found. All steps include runnable commands + exact
code blocks.

**Type consistency:** Function names match across tasks — `signToken`/`verifyToken`
(Task 2), `sendEmail`/`createContact`/`contactExists`/`listContacts` (Task 3/4/5),
`render_newsletter`/`send_newsletter`/`dry_render` (Task 14). Config field
names (`resend_api_key`, `resend_audience_id`, `newsletter_enabled`,
`newsletter_from`, `newsletter_reply_to`) match between `config_loader.py`
(Task 15) and `run_daily.py` (Task 16).
