const enc = new TextEncoder();

/** Hex HMAC-SHA256 over `<timestamp>.<body>` — byte-identical to prospector.web.ingest.sign. */
export async function sign(secret: string, timestamp: string, body: Uint8Array): Promise<string> {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const prefix = enc.encode(`${timestamp}.`);
  const data = new Uint8Array(prefix.length + body.length);
  data.set(prefix);
  data.set(body, prefix.length);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, data));
  return Array.from(mac, (b) => b.toString(16).padStart(2, "0")).join("");
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export const MIN_SECRET_LENGTH = 32;

export async function verify(secret: string, headers: Headers, body: Uint8Array, nowSeconds: number): Promise<boolean> {
  if (!secret || secret.length < MIN_SECRET_LENGTH) return false; // a guessable secret would let anyone mail the owner
  const ts = headers.get("X-Prospector-Timestamp");
  const sig = headers.get("X-Prospector-Signature") ?? "";
  if (!ts || !/^\d+$/.test(ts) || !sig.startsWith("sha256=")) return false;
  if (Math.abs(nowSeconds - Number(ts)) > 300) return false;
  return timingSafeEqual(sig.slice(7), await sign(secret, ts, body));
}
