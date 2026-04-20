// Cloudflare Worker: handles newsletter signup, double-opt-in confirmation,
// and serves subscriber count.
import type { Env } from "./env";
import { signToken } from "./jwt";
import { sendEmail, contactExists } from "./resend";
import { confirmEmailHtml, confirmEmailText } from "./confirm-email";

// CORS policy:
//   GET /count   — wildcard origin is fine (public, read-only)
//   POST /subscribe — Task 3 should scope Allow-Origin to env.SITE_URL;
//                     wildcard is intentional only while placeholder returns 501.
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
