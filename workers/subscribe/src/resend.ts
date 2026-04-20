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
    throw new Error(`Resend /emails ${resp.status}: ${body.slice(0, 200)}`);
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
  throw new Error(`Resend contacts ${resp.status}: ${body.slice(0, 200)}`);
}

export async function contactExists(env: Env, email: string): Promise<boolean> {
  const resp = await fetch(
    `${BASE}/audiences/${env.RESEND_AUDIENCE_ID}/contacts/${encodeURIComponent(email)}`,
    { headers: { Authorization: `Bearer ${env.RESEND_API_KEY}` } },
  );
  if (resp.ok) return true;
  if (resp.status === 404) return false;
  // Any other non-ok status is an upstream issue — let the caller's try/catch
  // log it and fall through so we send the confirm anyway.
  throw new Error(`contactExists unexpected ${resp.status}`);
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
