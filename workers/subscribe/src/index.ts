// Cloudflare Worker: handles newsletter signup, double-opt-in confirmation,
// and serves subscriber count.
import type { Env } from "./env";
import { signToken, verifyToken } from "./jwt";
import { sendEmail, contactExists, createContact, listContacts } from "./resend";
import { confirmEmailHtml, confirmEmailText } from "./confirm-email";
import { successPage, expiredPage, errorPage } from "./confirm-page";

// CORS policy:
//   GET /count      → PUBLIC_CORS (wildcard; public read-only)
//   POST /subscribe → siteCors(env.SITE_URL) (origin-scoped to prevent
//                     third-party form embedding)
const PUBLIC_CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function siteCors(siteUrl: string) {
  return {
    "Access-Control-Allow-Origin": siteUrl,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: PUBLIC_CORS });
    }

    if (request.method === "POST" && url.pathname === "/subscribe") {
      let body: { email?: unknown; website?: unknown; turnstileToken?: unknown };
      try {
        body = await request.json();
      } catch {
        return json({ error: "invalid_body" }, 400, siteCors(env.SITE_URL));
      }

      // Honeypot — real users leave `website` blank.
      if (typeof body.website === "string" && body.website.length > 0) {
        return json({ status: "pending" }, 200, siteCors(env.SITE_URL)); // silently drop
      }

      const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
      if (!isValidEmail(email)) return json({ error: "invalid_email" }, 400, siteCors(env.SITE_URL));

      // Already subscribed? Don't re-send confirmation, but don't leak existence
      // — return the same shape as a fresh signup.
      try {
        if (await contactExists(env, email)) {
          return json({ status: "pending" }, 200, siteCors(env.SITE_URL));
        }
      } catch (e) {
        console.error("contactExists failed", e);
        // Fall through — still send confirmation. Worst case we double-confirm.
      }

      const token = await signToken(email, env.SUBSCRIPTION_SECRET);
      const confirmUrl = `${url.origin}/confirm?token=${encodeURIComponent(token)}`;

      try {
        await sendEmail(env, {
          to: email,
          subject: "Confirm your subscription to The Daily Paper",
          html: confirmEmailHtml(confirmUrl),
          text: confirmEmailText(confirmUrl),
          from: env.FROM_ADDRESS,
          replyTo: env.REPLY_TO || undefined,
        });
      } catch (e) {
        console.error("sendEmail failed", e);
        return json({ error: "upstream_unavailable" }, 502, siteCors(env.SITE_URL));
      }

      return json({ status: "pending" }, 200, siteCors(env.SITE_URL));
    }

    if (request.method === "GET" && url.pathname === "/confirm") {
      const token = url.searchParams.get("token") || "";
      const html = (body: string, status = 200) =>
        new Response(body, { status, headers: { "Content-Type": "text/html; charset=utf-8" } });

      const v = await verifyToken(token, env.SUBSCRIPTION_SECRET);
      if (!v.ok) return html(expiredPage(env.SITE_URL), 400);

      try {
        await createContact(env, v.email);
      } catch (e) {
        console.error("createContact failed", e);
        return html(errorPage(), 502);
      }
      // Best-effort cache invalidation — failure is non-fatal.
      try {
        await env.SUBSCRIBE_CACHE.delete("count");
      } catch (kvErr) {
        console.error("KV delete failed (non-fatal)", kvErr);
      }
      return html(successPage(env.SITE_URL), 200);
    }

    if (request.method === "GET" && url.pathname === "/count") {
      const cached = await env.SUBSCRIBE_CACHE.get("count");
      if (cached !== null) {
        return json({ count: Number(cached) }, 200, PUBLIC_CORS);
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
            ...PUBLIC_CORS,
          },
        });
      } catch (e) {
        console.error("listContacts failed", e);
        return json({ error: "upstream_unavailable" }, 502, PUBLIC_CORS);
      }
    }

    return new Response("Not found", { status: 404 });
  },
};

function json(obj: unknown, status: number, corsHeaders: Record<string, string>): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

function isValidEmail(e: string): boolean {
  // Purposely loose — Resend does the real validation.
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e) && e.length <= 254;
}
