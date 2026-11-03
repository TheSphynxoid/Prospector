import { sign, verify } from "./sign";

export interface Env {
  INGEST_URL: string;
  FROM_ADDRESS: string;
  OWNER_EMAIL: string;
  BRIDGE_SECRET: string;
  ACCESS_CLIENT_ID: string;
  ACCESS_CLIENT_SECRET: string;
  SPOOL: R2Bucket;
  RETRY_QUEUE: Queue<Spooled>;
  EMAIL: SendEmail;
}

interface Spooled {
  key: string;
  receivedAt: number;
}

const RETRY_WINDOW_MS = 24 * 3600_000;
const RETRY_DELAY_SECONDS = 600;
const MAX_DIGEST_BYTES = 1024 * 1024;

async function postToIngest(env: Env, raw: Uint8Array): Promise<boolean> {
  const ts = String(Math.floor(Date.now() / 1000));
  try {
    const resp = await fetch(env.INGEST_URL, {
      method: "POST",
      body: raw,
      headers: {
        "Content-Type": "message/rfc822",
        "CF-Access-Client-Id": env.ACCESS_CLIENT_ID,
        "CF-Access-Client-Secret": env.ACCESS_CLIENT_SECRET,
        "X-Prospector-Timestamp": ts,
        "X-Prospector-Signature": "sha256=" + (await sign(env.BRIDGE_SECRET, ts, raw)),
      },
    });
    return resp.ok;
  } catch (e) {
    console.error("ingest POST failed", e);
    return false;
  }
}

/** Inbound alert email → Prospector. On failure the raw MIME is spooled to R2 (queue messages cap at 128 KB). */
export async function handleEmail(message: ForwardableEmailMessage, env: Env): Promise<void> {
  const raw = new Uint8Array(await new Response(message.raw).arrayBuffer());
  if (await postToIngest(env, raw)) return;
  const key = `mail/${Date.now()}-${crypto.randomUUID()}`;
  await env.SPOOL.put(key, raw);
  await env.RETRY_QUEUE.send({ key, receivedAt: Date.now() });
}

export async function handleQueueMessage(msg: Message<Spooled>, env: Env): Promise<void> {
  const { key, receivedAt } = msg.body;
  if (Date.now() - receivedAt > RETRY_WINDOW_MS) {
    console.error(`dropping spooled mail ${key}: undeliverable for 24h`);
    await env.SPOOL.delete(key);
    msg.ack();
    return;
  }
  const obj = await env.SPOOL.get(key);
  if (!obj) {
    msg.ack();
    return;
  }
  if (await postToIngest(env, new Uint8Array(await obj.arrayBuffer()))) {
    await env.SPOOL.delete(key);
    msg.ack();
  } else {
    msg.retry({ delaySeconds: RETRY_DELAY_SECONDS });
  }
}

/** POST /digest from Prospector → email to the owner via the Email Service binding. */
export async function handleDigest(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (request.method !== "POST" || url.pathname !== "/digest") return new Response("not found", { status: 404 });
  const body = new Uint8Array(await request.arrayBuffer());
  if (body.length > MAX_DIGEST_BYTES) return new Response("too large", { status: 413 });
  if (!(await verify(env.BRIDGE_SECRET, request.headers, body, Math.floor(Date.now() / 1000)))) {
    return new Response("bad signature", { status: 401 });
  }
  let digest: { subject?: string; text?: string; html?: string };
  try {
    digest = JSON.parse(new TextDecoder().decode(body));
  } catch {
    return new Response("bad json", { status: 400 });
  }
  if (!digest.subject || !digest.text || !digest.html) return new Response("missing fields", { status: 400 });
  await env.EMAIL.send({
    to: env.OWNER_EMAIL,
    from: { email: env.FROM_ADDRESS, name: "Prospector" },
    subject: digest.subject,
    text: digest.text,
    html: digest.html,
  });
  return new Response(null, { status: 202 });
}

export default {
  email: (message, env) => handleEmail(message, env),
  fetch: (request, env) => handleDigest(request, env),
  async queue(batch, env) {
    for (const msg of batch.messages) await handleQueueMessage(msg, env);
  },
} satisfies ExportedHandler<Env, Spooled>;
