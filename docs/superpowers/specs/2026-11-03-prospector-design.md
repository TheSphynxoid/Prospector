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
2. **Alert mailbox (IMAP)** — the owner configures job alerts on closed sites
   (LinkedIn, Indeed, Welcome to the Jungle, Malt, Tanitjobs) to a dedicated
   mailbox; Prospector parses the alert emails. Legitimate coverage of sites that
   cannot be scraped.
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
| `notify/` | Daily digest via Telegram bot and/or email | `store` |
| `web/` | FastAPI + HTMX dashboard, login-protected | `store` |
| `scheduler` | APScheduler jobs, all in `Africa/Tunis` timezone | all modules |

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
- Provider: the owner's low-cost subscription via an OpenAI-compatible API,
  configured by `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`. Provider ToS must
  allow API use outside coding tools — verify before enabling.
- Strict JSON output: `verdict` (`strong|maybe|weak`), `fit_summary`
  (≤ 2 sentences), `lead_with_project`, `red_flags[]`, `pay_estimate` (if missing).
- Cached by hash of lead content; a lead is never re-scored unless its content changes.

### Feedback learning

Nightly job recomputes rule weights from feedback counts and refreshes the
positive/negative example sets. No model training.

## 6. Data flow

1. **Fetch** — per-source intervals: APIs/RSS 2–6 h, mailbox 30 min, scrapers
   daily. Timeouts, identifying user-agent, robots.txt.
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
- Single-user login (password hash in `.env`), HTTPS via Caddy.

## 8. Error handling

- Adapters run isolated; one failing source never blocks others. Errors
  recorded in `SourceHealth`; 3 consecutive failures → paused and flagged,
  auto-retry daily.
- Parser drift: a source returning zero leads, or > 50 % leads missing key
  fields, raises a drift warning in the digest.
- LLM unavailable / over cap / invalid JSON: lead keeps stage-1 score, marked
  unreviewed; one repair retry for invalid JSON; digest always sends.
- Secrets (Telegram token, IMAP credentials, LLM key, dashboard password hash)
  only in server `.env`, never committed; `.env.example` documents them.
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
- Production monitoring = the source-health page + digest warnings.

## 10. Deployment

- `docker-compose.yml`: `prospector` (app + scheduler) and `caddy`; SQLite on a
  mounted volume; memory limit ~3 GB.
- Embedding model downloaded once into a volume at first start.
- Timezone for all schedules explicitly `Africa/Tunis` (server is in Sydney).

## 11. Open items for the owner

- Name of the low-cost LLM provider (to confirm API access + ToS).
- Digest channel: Telegram, email, or both.
- Dedicated alert mailbox to create (and which alert sites to subscribe).
- Dashboard domain (e.g. `prospector.thesphynx.net`).
