// Cloudflare Worker: handles newsletter signup, double-opt-in confirmation,
// and serves subscriber count.
import type { Env } from "./env";

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
