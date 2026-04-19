// Cloudflare Worker: receives Telegram webhook, parses `/video <arxiv_id>`,
// and triggers the GitHub Actions `video.yml` workflow via workflow_dispatch.
//
// Deploy with:
//   cd workers/telegram-video
//   npx wrangler deploy
//
// Register the webhook (one-off) after deploy:
//   curl -sS "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-worker>.workers.dev/"
//
// Required secrets (set with `wrangler secret put <NAME>`):
//   TELEGRAM_BOT_TOKEN    — the bot token (for replies)
//   TELEGRAM_WEBHOOK_SECRET — random string, also sent in Telegram setWebhook's `secret_token`
//   GH_TOKEN              — GitHub PAT with `repo` scope to trigger workflow_dispatch
//   GH_OWNER              — e.g. "akthecoders"
//   GH_REPO               — e.g. "thedailypaper"
//   ALLOWED_CHAT_IDS      — comma-separated list of chat_ids allowed to trigger, e.g. "1812483114"

export interface Env {
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_WEBHOOK_SECRET: string;
  GH_TOKEN: string;
  GH_OWNER: string;
  GH_REPO: string;
  ALLOWED_CHAT_IDS: string;
}

interface TgUpdate {
  message?: {
    chat: { id: number };
    text?: string;
    message_id: number;
  };
}

const HELP = `Usage:
  /video <arxiv_id>           — render 720p (default)
  /video <arxiv_id> l|m|h     — quality preset
Example: /video 2604.14885
Example: /video 2604.14885 h`;

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "POST") {
      return new Response("ok", { status: 200 });
    }

    // Telegram webhook secret verification (if configured)
    if (env.TELEGRAM_WEBHOOK_SECRET) {
      const hdr = request.headers.get("x-telegram-bot-api-secret-token");
      if (hdr !== env.TELEGRAM_WEBHOOK_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
    }

    let update: TgUpdate;
    try {
      update = await request.json();
    } catch {
      return new Response("bad json", { status: 400 });
    }

    const msg = update.message;
    if (!msg?.text) {
      return new Response("ignored", { status: 200 });
    }

    // Allowlist chat_id
    const allowed = env.ALLOWED_CHAT_IDS.split(",").map((s) => s.trim());
    if (!allowed.includes(String(msg.chat.id))) {
      await tgReply(env, msg.chat.id, "This bot is private. Ask the owner to allowlist your chat_id.");
      return new Response("forbidden", { status: 200 });
    }

    const text = msg.text.trim();

    if (text === "/start" || text === "/help") {
      await tgReply(env, msg.chat.id, HELP);
      return new Response("ok", { status: 200 });
    }

    // /video <id> [quality]
    const m = /^\/video\s+([\w.\/-]+)(?:\s+([lmh]))?\s*$/i.exec(text);
    if (!m) {
      // Silent on anything that's not a /video command.
      return new Response("ignored", { status: 200 });
    }

    const arxivId = m[1];
    const quality = (m[2] || "m").toLowerCase();

    try {
      await triggerWorkflow(env, arxivId, quality, String(msg.chat.id));
      await tgReply(
        env,
        msg.chat.id,
        `🎬 Queued video render for ${arxivId} (quality=${quality}).\nTakes ~5–10 min. I'll reply when it's ready.`,
      );
    } catch (e: any) {
      await tgReply(env, msg.chat.id, `❌ Failed to queue: ${e?.message || "unknown"}`);
    }

    return new Response("ok", { status: 200 });
  },
};

async function tgReply(env: Env, chatId: number, text: string) {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
}

async function triggerWorkflow(env: Env, arxivId: string, quality: string, chatId: string) {
  const url = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/video.yml/dispatches`;
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      authorization: `Bearer ${env.GH_TOKEN}`,
      "user-agent": "thedailypaper-video-worker",
    },
    body: JSON.stringify({
      ref: "main",
      inputs: {
        arxiv_id: arxivId,
        quality,
        notify_chat_id: chatId,
      },
    }),
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`GitHub API ${resp.status}: ${body.slice(0, 200)}`);
  }
}
