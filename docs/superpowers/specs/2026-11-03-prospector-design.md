# Prospector — Opportunity Finder (v1) Design

Date: 2026-11-03
Status: draft, awaiting owner review

## 1. Purpose

Prospector is an always-on personal system that finds income opportunities in
computer science — jobs, freelance gigs, bounties, PFE offers and AI-training
work — scores them against the owner's profile and projects, and delivers the
best ones as a daily digest plus a browsable dashboard.

It is sub-project 1 of 3:

1. **Opportunity finder** (this spec)
2. Application helper — tailored CV/proposal drafts and application tracking (later spec)
3. Open-source & portfolio pass — publishing projects as lead magnets (later, mostly cleanup work)

### Success criteria

- Relevant leads arrive every day without manual searching.
- Leads are pre-filtered and ranked; the top 10 in the digest are mostly worth reading.
- Ranking improves from the owner's feedback (★ / dismiss / applied).
- Running cost is effectively zero beyond the existing server and LLM subscription.

### Non-goals (v1)

- Auto-applying or sending any message on the owner's behalf — **never**; the owner acts on every lead.
- Application drafting and tracking (sub-project 2).
- Multiple users / multi-tenancy.
- Scraping sites whose terms forbid it (LinkedIn, Indeed, Malt, Welcome to the Jungle).

## 2. Scope of opportunities

All four target types are in scope:

| Kind | Examples |
|---|---|
| Remote, paid abroad | Remote jobs/contracts for EU, US, Gulf, AU companies |
| Local Tunisia | Jobs, internships, PFE offers |
| Relocation abroad | Jobs or paid PFEs abroad (e.g. France, Germany) |
| Gigs & bounties | Freelance platforms, bug bounties, OSS bounties, AI-training work |

`Lead.kind` ∈ `job | contract | gig | bounty | pfe | ai_training`.

## 3. Sources (v1)

Three acquisition modes, each a plugin adapter:

1. **Official APIs / RSS** — Remotive, RemoteOK, Himalayas, Arbeitnow, Adzuna
   (country passed explicitly: fr, de, gb, au, …), Hacker News "Who is hiring"
   (Algolia API), Algora + GitHub issues labelled bounty, Freelancer.com.
2. **Alert address (push, no mailbox)** — the owner points job alerts on closed
   sites (LinkedIn, Indeed, Welcome to the Jungle, Malt, Tanitjobs) at
   `alerts@prospector.thesphynx.net`. Cloudflare Email Routing (subdomain MX
   only — the apex Zoho MX records are untouched) hands each message to the
   `mail-bridge` Worker, which POSTs the raw MIME to Prospector's ingest
   endpoint (see §4.3). Prospector parses the alert emails with per-sender
   parsers. Legitimate coverage of sites that cannot be scraped. A
   confirmation email from an alert site (verify-your-address links) is
   surfaced on the dashboard for the owner to click manually — never
   auto-clicked.
3. **Polite scrapers** — only where terms allow (candidate: Keejob, Tunisian
   national employment portal). robots.txt respected, identifying user-agent,
   at most daily.

v1 ships 8–10 adapters. Adding a source = one file implementing the adapter
interface + a config entry.

If a Tunisian source blocks or alters content for Australian IPs, that adapter
may later run on the owner's local machine and push to the server's ingest
endpoint. Not in v1.

## 4. Architecture

Python 3.12 modular monolith, one process, Docker Compose on the owner's Linux
server in Sydney (32 GB RAM, no GPU; container capped at ~3 GB).

| Module | Responsibility | Depends on |
|---|---|---|
| `sources/` | Adapters: `fetch() -> list[RawLead]` | httpx, imaplib, feed/HTML parsers |
| `normalize/` | `RawLead` → `Lead`; cross-source dedupe | `sources` output |
| `profile/` | Loads `profile.yaml` (skills, projects, targets, filters, keywords) | — |
| `rank/` | Stage 1 (free) + stage 2 (LLM) scoring; feedback weighting | `profile`, `llm`, `store` |
| `llm/` | OpenAI-compatible client, provider from config, daily cap, cache | — |
| `store/` | SQLite persistence | — |
| `notify/` | Daily digest via Telegram bot **and** email | `store` |
| `web/` | FastAPI + HTMX dashboard + `/ingest/mail` endpoint | `store` |
| `scheduler` | APScheduler jobs, all in `Africa/Tunis` timezone | all modules |
| `mail-bridge/` (Cloudflare Worker, TypeScript) | Inbound: email → POST raw MIME to Prospector. Outbound: receives the digest from Prospector and sends it via the `send_email` binding to the owner's verified Zoho address | Cloudflare Email Routing |

### 4.1 Data model (core)

- `RawLead`: source_id, external_id, url, title, company, body, location_text,
  pay_text, posted_at, fetched_at, raw_payload.
- `Lead`: id, canonical_url, title, company, kind, remote (`yes|no|hybrid`),
  remote_region (e.g. "EU only"), locations[], pay_min, pay_max, pay_currency,
  pay_period, languages[], deadline, posted_at, sources[] (all sources it was
  seen on), status (`new|starred|dismissed|applied|filtered`), filter_reason.
- `Score`: lead_id, stage1_score, stage1_breakdown (JSON), stage2 (JSON or null),
  reviewed (bool), scored_at.
- `Feedback`: lead_id, action, at.
- `SourceHealth`: source_id, last_run, last_ok, consecutive_failures, last_count,
  last_error, paused.

### 4.2 Profile (`profile.yaml`)

Skills (weighted), projects (each with a 2–4 sentence write-up used for
embedding similarity and for "lead with this project"), targets (kinds,
regions), hard filters (unpaid excluded, minimum pay per period/currency,
languages FR/EN/AR, blocked keywords/companies), boost keywords
(e.g. Go, C++, systems, travel-tech, NUMA, Spring, .NET).

Initial projects to describe: room-mapping/packing engine, SRV project
orchestration engine, Furrballs (NUMA-aware cache, REMARC), BoosterBC Go
supplier connectors, DataMart, Hubris Engine, stepwise.

### 4.3 Network & access

- Server reached for deployment over **Tailscale** (SSH).
- Public hostname `prospector.thesphynx.net` served by the existing
  **cloudflared** tunnel and protected by **Cloudflare Access** (owner's
  identity only). No ports opened on the server; no reverse proxy needed —
  the tunnel terminates TLS.
- The app listens only on localhost (for cloudflared) and the Tailscale
  interface. Auth rule in the app: requests from the tailnet range
  (`100.64.0.0/10`) are trusted; all others must carry a valid
  `Cf-Access-Jwt-Assertion` (verified against the team's Access certs and
  application AUD). Defense in depth if a tunnel/Access rule is misconfigured.
- `/ingest/mail`: Access application with a **service-token** policy; the
  Worker sends `CF-Access-Client-Id/Secret`. The app additionally requires an
  HMAC-SHA256 signature header over the body with a shared secret, and caps
  body size (5 MB).
- Outbound digest email: Prospector POSTs the rendered digest to the Worker
  (`/digest`, same shared-secret HMAC); the Worker sends it with `send_email`
  to the owner's verified destination address.

## 5. Ranking

### Stage 1 — every new lead, free

1. Hard filters → status `filtered` with `filter_reason` (visible in a
   "filtered" tab so false negatives can be spotted).
2. Embedding similarity: lead text vs profile + project write-ups, using
   **fastembed with `intfloat/multilingual-e5-base`** (ONNX, CPU-only; FR/EN/AR).
   No GPU needed — a few hundred leads/day embed in seconds.
3. Rule boosts: keyword matches, pay level, remote, kind preferences, freshness.
4. Feedback adjustment: similarity to ★ / applied leads (+) and dismissed
   leads (−), as nearest-neighbour bonus/penalty.

`stage1_score` in [0, 1] with a stored breakdown.

### Stage 2 — top N per day, LLM

- Top unreviewed leads above a threshold, up to a daily cap (default 20).
- Provider: **OpenCode Go** via its OpenAI-compatible endpoint
  (`LLM_BASE_URL=https://opencode.ai/inference/go/openai/v1`), configured by
  `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`; swappable to any
  OpenAI-compatible provider by config alone.
- Default model: a cheap fast one (`glm-5.3-flash`, fallback
  `qwen3.8-flash`); model IDs validated at startup against `/v1/models`.
- OpenCode Go is described as designed for coding agents and monitors traffic
  for abuse. To stay a good citizen: identifying `User-Agent`
  (`prospector/<version>`), a stable `x-opencode-session` header per daily
  run, low volume (cap 20/day), and no retries beyond the one repair retry.
  If the provider objects, switch provider in config.
- Strict JSON output: `verdict` (`strong|maybe|weak`), `fit_summary`
  (≤ 2 sentences), `lead_with_project`, `red_flags[]`, `pay_estimate` (if missing).
- Cached by hash of lead content; a lead is never re-scored unless its content changes.

### Feedback learning

Nightly job recomputes rule weights from feedback counts and refreshes the
positive/negative example sets. No model training.

## 6. Data flow

1. **Fetch / receive** — pull sources on per-source intervals: APIs/RSS 2–6 h,
   scrapers daily (timeouts, identifying user-agent, robots.txt). Alert emails
   arrive by push at `/ingest/mail`, are stored raw, and are parsed into
   `RawLead`s by the `alerts` adapter on the next 15-minute tick.
2. **Normalize + dedupe** — dedupe by canonical URL, then fuzzy
   title + company match; duplicates merge into `Lead.sources`. Raw payloads kept 30 days.
3. **Stage 1 rank** on new leads.
4. **Stage 2 rank** within daily cap.
5. **Digest at 08:00 Africa/Tunis** — top 10 new since last digest; ★ leads
   with deadlines within 3 days; source-health warnings; dashboard link.
6. **Feedback** from dashboard → `store`; nightly reweighting.

## 7. Dashboard

- Lead list: filters by kind, remote, region, score, status, source; sort by score/date.
- Lead detail: normalized fields, score breakdown, LLM verdict, original link, all sources.
- Actions: ★, dismiss, applied (one click, HTMX).
- Tabs: new, starred, applied, filtered.
- Source health page.
- "Needs you" panel: alert-site confirmation emails and paused sources.
- No app-level password: access via Tailscale or Cloudflare Access (§4.3).

## 8. Error handling

- Adapters run isolated; one failing source never blocks others. Errors
  recorded in `SourceHealth`; 3 consecutive failures → paused and flagged,
  auto-retry daily.
- Parser drift: a source returning zero leads, or > 50 % leads missing key
  fields, raises a drift warning in the digest.
- LLM unavailable / over cap / invalid JSON: lead keeps stage-1 score, marked
  unreviewed; one repair retry for invalid JSON; digest always sends.
- Secrets (Telegram token, LLM key, mail-bridge HMAC secret, Access AUD/team)
  only in server `.env` and Worker secrets, never committed; `.env.example`
  documents them.
- Ingest endpoint unavailable (server down): the Worker retries with backoff
  for up to 24 h by keeping failed messages in a Cloudflare Queue, then drops
  with a log entry.
- Digest delivery: Telegram and email are sent independently; failure of one
  is reported through the other.
- Nightly SQLite backup, 14-day retention.

## 9. Testing

- Adapter tests against recorded fixtures (`tests/fixtures/`: JSON, RSS,
  `.eml`, HTML) — offline, catch parser breakage.
- Table-driven normalize/dedupe tests: same job on 3 sites, TND/EUR/
  "competitive" pay, "remote (EU only)", French postings.
- Ranking tests on a small hand-labelled set; snapshot test of the stage-2
  prompt and JSON parsing with a fake LLM.
- End-to-end smoke test: one cycle with fake sources + fake LLM, digest text
  and dashboard pages render.
- Auth tests: tailnet source allowed; missing/invalid Access JWT rejected;
  `/ingest/mail` rejects bad HMAC and oversize bodies.
- `mail-bridge` Worker: vitest with the Workers pool — forwards MIME with
  correct signature, queues on ingest failure, `/digest` rejects bad HMAC.
- Production monitoring = the source-health page + digest warnings.

## 10. Deployment

- `docker-compose.yml`: single `prospector` service (app + scheduler); SQLite
  on a mounted volume; memory limit ~3 GB; ports bound to localhost and the
  Tailscale IP only.
- Existing cloudflared tunnel gets an ingress rule for
  `prospector.thesphynx.net → localhost:<port>`; Cloudflare Access apps for
  the dashboard (owner identity) and `/ingest/mail` (service token).
- `mail-bridge` Worker deployed with wrangler; Email Routing enabled for the
  `prospector.thesphynx.net` subdomain; owner's Zoho address verified as a
  destination.
- Embedding model downloaded once into a volume at first start; CPU-only
  (no GPU on the server).
- Timezone for all schedules explicitly `Africa/Tunis` (server is in Sydney).
- Deploys over Tailscale SSH: `git pull && docker compose up -d --build`.

## 11. Decisions (resolved 2026-11-03)

- LLM: OpenCode Go, OpenAI-compatible endpoint, cheap flash model (§5).
- Digest: both Telegram and email, plus the dashboard.
- Alerts: Cloudflare Email Routing on the subdomain → Worker → ingest (§3, §4.3).
- Host: `prospector.thesphynx.net` via cloudflared + Cloudflare Access;
  Tailscale for direct access and deployment.

## 12. Owner setup tasks (manual, done by the owner)

- Create the OpenCode Go API key; create the Telegram bot via @BotFather.
- Verify the Zoho address as an Email Routing destination (click the link).
- Configure the Cloudflare Access policies (owner identity; service token).
- Subscribe job alerts on LinkedIn, Indeed, Welcome to the Jungle, Malt,
  Tanitjobs to `alerts@prospector.thesphynx.net`.
