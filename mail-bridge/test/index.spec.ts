import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { handleDigest, handleEmail, handleQueueMessage, type Env } from "../src/index";
import { sign } from "../src/sign";

const enc = new TextEncoder();

function fakeEnv() {
  const store = new Map<string, Uint8Array>();
  const queued: unknown[] = [];
  const sent: unknown[] = [];
  const env: Env = {
    INGEST_URL: "https://prospector.test/ingest/mail",
    FROM_ADDRESS: "digest@prospector.test",
    OWNER_EMAIL: "owner@example.com",
    BRIDGE_SECRET: "sec",
    ACCESS_CLIENT_ID: "cid",
    ACCESS_CLIENT_SECRET: "csecret",
    SPOOL: {
      put: async (k: string, v: ArrayBuffer | Uint8Array) => { store.set(k, new Uint8Array(v)); },
      get: async (k: string) => (store.has(k) ? { arrayBuffer: async () => store.get(k)!.buffer } : null),
      delete: async (k: string) => { store.delete(k); },
    },
    RETRY_QUEUE: { send: async (m: unknown) => { queued.push(m); } },
    EMAIL: { send: async (m: unknown) => { sent.push(m); return { messageId: "m1" }; } },
  } as unknown as Env;
  return { env, store, queued, sent };
}

function message(raw: string) {
  return { raw: new Response(raw).body!, rawSize: raw.length, from: "a@b", to: "alerts@x" };
}

describe("sign", () => {
  it("matches python vector", async () => {
    // Same vector as tests/web/test_ingest.py::test_sign_cross_language_vector
    expect(await sign("s", "1700000000", enc.encode("hello"))).toBe(
      "572a25936663b163a3e39109afc634683bd8a51ddc845600f628e37b49218bf1");
  });
});

describe("email", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("forwards with signature and access headers", async () => {
    const { env, queued } = fakeEnv();
    const fetchMock = vi.fn(async () => new Response(null, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    await handleEmail(message("RAW MIME") as never, env);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const h = new Headers(init.headers);
    expect(url).toBe(env.INGEST_URL);
    expect(h.get("CF-Access-Client-Id")).toBe("cid");
    expect(h.get("CF-Access-Client-Secret")).toBe("csecret");
    const ts = h.get("X-Prospector-Timestamp")!;
    expect(h.get("X-Prospector-Signature")).toBe("sha256=" + (await sign("sec", ts, enc.encode("RAW MIME"))));
    expect(queued).toEqual([]);
  });

  it("spools to R2 and queues on 503", async () => {
    const { env, store, queued } = fakeEnv();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 503 })));
    await handleEmail(message("RAW MIME") as never, env);
    expect(store.size).toBe(1);
    expect(queued).toHaveLength(1);
  });

  it("spools when fetch throws", async () => {
    const { env, queued } = fakeEnv();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("network"); }));
    await handleEmail(message("RAW") as never, env);
    expect(queued).toHaveLength(1);
  });
});

describe("queue", () => {
  afterEach(() => vi.unstubAllGlobals());

  function msg(body: { key: string; receivedAt: number }) {
    return { body, ack: vi.fn(), retry: vi.fn() };
  }

  it("drops after 24h", async () => {
    const { env, store } = fakeEnv();
    store.set("k", enc.encode("RAW"));
    const m = msg({ key: "k", receivedAt: Date.now() - 25 * 3600_000 });
    await handleQueueMessage(m as never, env);
    expect(m.ack).toHaveBeenCalled();
    expect(store.has("k")).toBe(false);
  });

  it("retries on failure", async () => {
    const { env, store } = fakeEnv();
    store.set("k", enc.encode("RAW"));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 502 })));
    const m = msg({ key: "k", receivedAt: Date.now() });
    await handleQueueMessage(m as never, env);
    expect(m.retry).toHaveBeenCalledWith({ delaySeconds: 600 });
    expect(store.has("k")).toBe(true);
  });

  it("delivers and cleans up on success", async () => {
    const { env, store } = fakeEnv();
    store.set("k", enc.encode("RAW"));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 202 })));
    const m = msg({ key: "k", receivedAt: Date.now() });
    await handleQueueMessage(m as never, env);
    expect(m.ack).toHaveBeenCalled();
    expect(store.has("k")).toBe(false);
  });
});

describe("digest", () => {
  let env: Env, sent: unknown[];
  beforeEach(() => ({ env, sent } = fakeEnv()));

  async function req(body: string, ts = String(Math.floor(Date.now() / 1000)), sig?: string) {
    sig ??= "sha256=" + (await sign("sec", ts, enc.encode(body)));
    return new Request("https://bridge.test/digest", {
      method: "POST", body,
      headers: { "X-Prospector-Timestamp": ts, "X-Prospector-Signature": sig },
    });
  }

  it("rejects bad signature", async () => {
    const r = await handleDigest(await req("{}", undefined, "sha256=" + "0".repeat(64)), env);
    expect(r.status).toBe(401);
    expect(sent).toEqual([]);
  });

  it("rejects stale timestamp", async () => {
    const r = await handleDigest(await req("{}", String(Math.floor(Date.now() / 1000) - 400)), env);
    expect(r.status).toBe(401);
  });

  it("sends email", async () => {
    const body = JSON.stringify({ subject: "S", text: "T", html: "<p>H</p>" });
    const r = await handleDigest(await req(body), env);
    expect(r.status).toBe(202);
    expect(sent).toEqual([{ to: "owner@example.com", from: { email: "digest@prospector.test", name: "Prospector" },
                            subject: "S", text: "T", html: "<p>H</p>" }]);
  });

  it("rejects wrong path and method", async () => {
    const r = await handleDigest(new Request("https://bridge.test/other"), env);
    expect(r.status).toBe(404);
  });
});
