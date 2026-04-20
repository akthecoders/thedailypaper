// Minimal HS256 JWT signer/verifier. Web Crypto only — no deps.

const ALG = { name: "HMAC", hash: "SHA-256" };
const TTL_SECONDS = 48 * 60 * 60; // 48h

interface Claims {
  email: string;
  iat: number; // issued-at, unix seconds
}

function b64urlEncode(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
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
  if (typeof claims.iat !== "number") return { ok: false, reason: "bad_claims" };
  const age = Math.floor(Date.now() / 1000) - claims.iat;
  if (age < 0 || age >= TTL_SECONDS) return { ok: false, reason: "expired" };
  if (typeof claims.email !== "string" || !claims.email.includes("@")) {
    return { ok: false, reason: "bad_email" };
  }
  return { ok: true, email: claims.email.toLowerCase() };
}
