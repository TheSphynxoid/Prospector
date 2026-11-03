# Prospector v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An always-on personal service that pulls CS jobs, gigs, bounties and PFE offers from many sources, ranks them against the owner's profile, and delivers a daily Telegram + email digest and an HTMX dashboard.

**Architecture:** Python 3.12 modular monolith (FastAPI app + APScheduler in one process, SQLite) in Docker on the owner's Sydney server, exposed via the existing cloudflared tunnel behind Cloudflare Access and over Tailscale. A small TypeScript Cloudflare Worker (`mail-bridge`) turns alert emails into signed POSTs and sends the email digest.

**Tech Stack:** Python 3.12, uv, FastAPI, Jinja2, HTMX 2.0.4 (vendored), httpx, pydantic v2 + pydantic-settings, APScheduler 3.x, fastembed (ONNX, CPU), numpy, rapidfuzz, selectolax, PyJWT[crypto], pytest, respx, time-machine. Worker: TypeScript, wrangler, mimetext, vitest + @cloudflare/vitest-pool-workers.

**Spec:** `docs/superpowers/specs/2026-11-03-prospector-design.md`

## Global Constraints

- Never send applications or messages on the owner's behalf; never auto-click confirmation links.
- All schedules use timezone `Africa/Tunis` explicitly (server clock is Sydney).
- Digest at 08:00 Africa/Tunis: top 10 new leads since last digest, ★ leads with deadline within 3 days, source-health warnings, dashboard link `https://prospector.thesphynx.net`.
- Stage-2 LLM daily cap default 20; one repair retry on invalid JSON, no other retries.
- LLM: `LLM_BASE_URL=https://opencode.ai/inference/go/openai/v1`, default model `glm-5.3-flash`, fallback `qwen3.8-flash`; `User-Agent: prospector/<version>`; header `x-opencode-session` stable per daily run.
- Embeddings: fastembed `intfloat/multilingual-e5-base`, CPU-only, `query: ` / `passage: ` prefixes.
- Pull intervals: APIs/RSS 2–6 h; scrapers daily; alert-mail parse tick every 15 min.
- Source pausing: 3 consecutive failures → paused, retried daily. Drift: 0 leads or > 50 % of leads missing title/url/body.
- Raw payloads kept 30 days; nightly SQLite backup, 14-day retention.
- Ingest body cap 5 MB; HMAC-SHA256 over `<timestamp>.<body>`, ±300 s window.
- Trusted network: `100.64.0.0/10` (tailnet). Everything else needs a valid `Cf-Access-Jwt-Assertion`. `/healthz` is the only exempt route.
- Container memory limit 3 GB. Secrets only in `.env` / Worker secrets; `.env.example` documents every variable.
- HTTP user-agent for sources: `prospector/<version> (+https://prospector.thesphynx.net)`; timeout 20 s; robots.txt respected for scrapers.

## Review Focus

1. Same posting seen with tracking params (`utm_*`, `ref`), `http` vs `https`, trailing slash, or on three boards → exactly one lead with all sources merged. *(Task 3)*
2. Messy pay text ("3k–4k €/mois", "1 500 TND", "Competitive", "$40/hr", "up to 120,000 USD") → parsed or `None`, never an exception. *(Task 3)*
3. LLM replies wrapped in ```` ```json ```` fences or prefixed with prose → parsed; unparseable after repair → lead stays "unreviewed", cycle continues. *(Task 6)*
4. Digest longer than Telegram's 4096-char limit, or titles containing `<`, `&`, `>` → split into multiple messages and HTML-escaped. *(Task 13)*
5. Alert email from an unknown sender, HTML-only, or in a non-UTF-8 charset → stored and surfaced as a "needs you: unparsed" item, never crashes the parse tick. *(Task 10)*

## File Structure

```
pyproject.toml, uv.lock, Dockerfile, docker-compose.yml, .env.example, profile.example.yaml, README.md
src/prospector/
  __init__.py            __version__
  config.py              Settings (pydantic-settings)
  models.py              Kind, Remote, Status, RawLead, Lead, Pay
  http.py                make_client()
  store/   schema.sql, db.py, leads.py, scores.py, feedback.py, health.py, mail.py, kv.py
  normalize/ url.py, pay.py, remote.py, kind.py, lang.py, normalize.py, dedupe.py
  profile/ model.py, filters.py
  rank/    embed.py, stage1.py, weights.py, stage2.py
  llm/     client.py
  sources/ base.py, runner.py, registry.py, robots.py,
           remotive.py, remoteok.py, himalayas.py, arbeitnow.py,
           adzuna.py, hn.py, github_bounties.py, freelancer.py, keejob.py,
           alerts/ __init__.py, parse.py, generic.py
  notify/  digest.py, telegram.py, email.py, run.py
  web/     app.py, auth.py, ingest.py, dashboard.py, templates/*.html, static/htmx.min.js, static/app.css
  pipeline.py, scheduler.py, __main__.py
tests/ (mirrors src; fixtures in tests/fixtures/<source>/)
mail-bridge/ package.json, wrangler.jsonc, src/index.ts, src/sign.ts, test/index.spec.ts
```

---

### Task 1: Project scaffold, settings and core models

**Files:**
- Create: `pyproject.toml`, `src/prospector/__init__.py`, `src/prospector/config.py`, `src/prospector/models.py`, `src/prospector/http.py`, `.gitignore`, `.env.example`
- Test: `tests/test_models.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `__version__ = "0.1.0"`
  - `class Kind(StrEnum)`: `JOB="job", CONTRACT="contract", GIG="gig", BOUNTY="bounty", PFE="pfe", AI_TRAINING="ai_training"`
  - `class Remote(StrEnum)`: `YES, NO, HYBRID, UNKNOWN` (lowercase values)
  - `class Status(StrEnum)`: `NEW, STARRED, DISMISSED, APPLIED, FILTERED`
  - `@dataclass(frozen=True) Pay(min: float|None, max: float|None, currency: str|None, period: Literal["hour","day","month","year","fixed"]|None)`
  - `@dataclass RawLead(source_id: str, external_id: str, url: str, title: str, body: str, company: str|None=None, location_text: str|None=None, pay_text: str|None=None, posted_at: datetime|None=None, deadline: date|None=None, kind_hint: Kind|None=None, raw_payload: str="", fetched_at: datetime=field(default_factory=utcnow))`
  - `@dataclass Lead(canonical_url, title, company, kind, remote, remote_region: str|None, locations: list[str], pay: Pay|None, languages: list[str], deadline, posted_at, body: str, content_hash: str, sources: list[str], status: Status=Status.NEW, filter_reason: str|None=None, id: int|None=None)`
  - `class Settings(BaseSettings)` with fields (env names in caps): `data_dir: Path="/data"`, `profile_path: Path`, `dashboard_url="https://prospector.thesphynx.net"`, `llm_base_url`, `llm_model="glm-5.3-flash"`, `llm_fallback_model="qwen3.8-flash"`, `llm_api_key: SecretStr`, `llm_daily_cap=20`, `stage2_threshold=0.55`, `telegram_token: SecretStr|None`, `telegram_chat_id: str|None`, `bridge_url: str|None`, `bridge_secret: SecretStr`, `access_team_domain: str`, `access_aud: str`, `adzuna_app_id/adzuna_app_key: str|None`, `github_token: SecretStr|None`, `enabled_sources: list[str]`, `embed_model="intfloat/multilingual-e5-base"`
  - `make_client() -> httpx.Client` (UA and 20 s timeout per Global Constraints)

- [ ] **Step 1:** `uv init --package --python 3.12`, add runtime deps and dev deps (`pytest respx time-machine`) from Tech Stack; configure pytest `testpaths=["tests"]`.
- [ ] **Step 2: Write failing tests**
  - `test_lead_defaults`: a `Lead` built without status has `status == Status.NEW` and `filter_reason is None`.
  - `test_kind_values`: `Kind("ai_training") is Kind.AI_TRAINING`.
  - `test_settings_from_env(monkeypatch)`: with `LLM_API_KEY`, `BRIDGE_SECRET`, `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, `PROFILE_PATH` set, `Settings().llm_daily_cap == 20` and `Settings().llm_model == "glm-5.3-flash"`.
  - `test_client_user_agent`: `make_client().headers["User-Agent"].startswith("prospector/0.1.0")`.
- [ ] **Step 3:** Run `uv run pytest -q` → FAIL (import errors).
- [ ] **Step 4:** Implement the interfaces above; write `.env.example` listing every Settings field with a comment; `.gitignore` covers `.env`, `data/`, `.venv/`.
- [ ] **Step 5:** `uv run pytest -q` → PASS.
- [ ] **Step 6:** Commit `feat: scaffold project, settings and core models`.

---

### Task 2: SQLite store

**Files:**
- Create: `src/prospector/store/{schema.sql,db.py,leads.py,scores.py,feedback.py,health.py,mail.py,kv.py}`
- Test: `tests/store/test_store.py`

**Interfaces:**
- Consumes: models from Task 1.
- Produces:
  - `connect(path: Path | str) -> sqlite3.Connection` — WAL mode, `foreign_keys=ON`, applies `schema.sql` idempotently. `":memory:"` allowed for tests.
  - `LeadRepo(conn)`: `insert(lead: Lead) -> int`; `get(id) -> Lead|None`; `by_canonical_url(url) -> Lead|None`; `recent_by_company(company_norm: str, days: int = 60) -> list[Lead]`; `add_source(id, source_id)`; `set_status(id, status, reason: str|None=None)`; `list(tab: Status, kind: Kind|None=None, remote: Remote|None=None, source: str|None=None, min_score: float|None=None, sort: Literal["score","date"]="score", limit=50, offset=0) -> list[LeadRow]` where `LeadRow(lead: Lead, stage1: float|None, stage2: dict|None)`; `new_since(ts: datetime, limit: int) -> list[LeadRow]` (status NEW, ordered by stage1 desc); `starred_with_deadline_within(days: int, today: date) -> list[LeadRow]`; `put_raw(lead_id, source_id, raw_payload)`; `prune_raw(older_than_days: int) -> int`.
  - `ScoreRepo(conn)`: `save_stage1(lead_id, score: float, breakdown: dict)`; `save_stage2(lead_id, result: dict)`; `save_embedding(lead_id, vec: np.ndarray)`; `embeddings(ids: list[int]) -> np.ndarray`; `top_unreviewed(threshold: float, limit: int) -> list[int]`.
  - `FeedbackRepo(conn)`: `record(lead_id, action: Literal["star","dismiss","applied","reset"])`; `positive_ids() -> list[int]` (latest action star/applied); `negative_ids() -> list[int]`; `count() -> int`.
  - `HealthRepo(conn)`: `get(source_id) -> SourceHealth`; `all() -> list[SourceHealth]`; `record_success(source_id, count: int, drift: bool)`; `record_failure(source_id, error: str) -> SourceHealth`; `set_paused(source_id, paused: bool)`. `SourceHealth(source_id, last_run, last_ok, consecutive_failures, last_count, last_error, paused, drift)`.
  - `MailRepo(conn)`: `insert(raw: bytes, received_at: datetime) -> int`; `pending() -> list[tuple[int, bytes]]`; `mark(id, state: Literal["parsed","unparsed","confirmation"], note: str|None=None, url: str|None=None)`; `needs_you() -> list[NeedsYouItem]`; `dismiss_needs_you(id)`.
  - `KV(conn)`: `get(key, default=None) -> Any` / `set(key, value)` (JSON-encoded).

- [ ] **Step 1: Write failing tests** — `test_insert_and_get_roundtrip` (pay and lists survive), `test_add_source_merges` (`sources == ["remotive","himalayas"]`), `test_list_filters_by_tab_and_kind`, `test_top_unreviewed_respects_threshold_and_limit`, `test_record_failure_counts_and_success_resets` (3 failures → `consecutive_failures == 3`; success → 0), `test_feedback_latest_action_wins` (star then dismiss → in `negative_ids` only), `test_prune_raw_older_than_30_days`, `test_kv_roundtrip`, `test_connect_is_idempotent` (connect twice on same file, no error).
- [ ] **Step 2:** `uv run pytest tests/store -q` → FAIL.
- [ ] **Step 3:** Implement. Lists/pay stored as JSON columns; embeddings as `float32` BLOB.
- [ ] **Step 4:** `uv run pytest tests/store -q` → PASS.
- [ ] **Step 5:** Commit `feat: sqlite store`.

---

### Task 3: Normalization and dedupe

**Files:**
- Create: `src/prospector/normalize/{url.py,pay.py,remote.py,kind.py,lang.py,normalize.py,dedupe.py}`
- Test: `tests/normalize/test_url.py`, `test_pay.py`, `test_remote.py`, `test_kind.py`, `test_lang.py`, `test_dedupe.py`

**Interfaces:**
- Produces:
  - `canonical_url(url: str) -> str` — https, lowercase host, strip `www.`, drop fragment, drop query keys `utm_*`, `ref`, `refId`, `trackingId`, `source`, `gclid`, `fbclid`; strip trailing slash; sort remaining query keys.
  - `parse_pay(text: str|None) -> Pay|None` — never raises. Currencies: `€|EUR`, `$|USD`, `£|GBP`, `TND|DT`, `AUD`, `CAD`; `k` suffix ×1000; spaces/commas as thousands separators; ranges with `-`, `–`, `to`, `à`; periods from `hr|hour|heure|/h` → hour, `day|jour` → day, `mo|month|mois` → month, `yr|year|an|annual|/a` → year; "up to X" → `min=None, max=X`; non-numeric ("Competitive", "DOE") → `None`.
  - `parse_remote(location_text: str|None, title: str, body: str) -> tuple[Remote, str|None]` — region extracted from patterns like `remote (EU only)`, `remote - US`, `télétravail`; hybrid/hybride → HYBRID.
  - `detect_kind(raw: RawLead) -> Kind` — `kind_hint` wins; else keywords: `pfe|stage de fin d'études|end-of-study internship` → PFE; `bounty` → BOUNTY; `freelance|contract|contrat|mission` → CONTRACT; `annotat|ai training|rlhf|evaluate model` → AI_TRAINING; default JOB.
  - `detect_languages(text: str) -> list[str]` — `"ar"` if Arabic script ≥ 10 % of letters; `"fr"` / `"en"` by stopword counts (≥ 3 hits); ordered by count.
  - `normalize(raw: RawLead) -> Lead` — strips HTML from body (selectolax `text()`), collapses whitespace, `content_hash = sha256(title|company|body)`, `sources=[raw.source_id]`.
  - `company_norm(name: str|None) -> str` — lowercase, strip legal suffixes (`inc, ltd, llc, sarl, sas, gmbh, sa`) and punctuation.
  - `is_duplicate(a: Lead, b: Lead) -> bool` — same `canonical_url`, or `company_norm` equal and `rapidfuzz.fuzz.token_set_ratio(a.title, b.title) >= 90`.

- [ ] **Step 1: Write failing tests (table-driven, `pytest.mark.parametrize`)**
  - URL: `"http://www.Remotive.com/jobs/1/?utm_source=x&ref=y#top"` and `"https://remotive.com/jobs/1"` → equal.
  - Pay: `"3k–4k €/mois"` → `Pay(3000, 4000, "EUR", "month")`; `"1 500 TND"` → `Pay(1500, 1500, "TND", None)`; `"$40/hr"` → `Pay(40, 40, "USD", "hour")`; `"up to 120,000 USD"` → `Pay(None, 120000, "USD", None)`; `"Competitive"` → `None`; `None` → `None`; `"€€€ ???"` → `None` (no exception).
  - Remote: `("Remote (EU only)", ...)` → `(Remote.YES, "EU only")`; `("Tunis, hybride", ...)` → `(Remote.HYBRID, None)`; `("Paris", ...)` → `(Remote.NO, None)`; `(None, "Backend dev", "")` → `(Remote.UNKNOWN, None)`.
  - Kind: title `"Stage PFE - Développeur Go"` → PFE; `kind_hint=Kind.BOUNTY` wins over title "Senior Engineer".
  - Lang: French paragraph → `["fr"]`; Arabic sentence → `["ar"]` first.
  - Dedupe: same title "Senior Go Engineer" vs "Senior Go Engineer (Remote)" at "Acme Inc." / "ACME" → True; different companies → False.
- [ ] **Step 2:** `uv run pytest tests/normalize -q` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `uv run pytest tests/normalize -q` → PASS.
- [ ] **Step 5:** Commit `feat: normalization and dedupe`.

---

### Task 4: Profile and hard filters

**Files:**
- Create: `src/prospector/profile/{model.py,filters.py}`, `profile.example.yaml`
- Test: `tests/profile/test_profile.py`

**Interfaces:**
- Produces:
  - Pydantic `Profile(skills: dict[str, float], projects: list[Project], targets: Targets, filters: Filters, boost_keywords: dict[str, float])`; `Project(name: str, writeup: str, tags: list[str] = [])`; `Targets(kinds: list[Kind], regions: list[str])`; `Filters(exclude_unpaid: bool = True, min_pay: list[MinPay] = [], languages: list[str] = ["fr","en","ar"], blocked_keywords: list[str] = [], blocked_companies: list[str] = [])`; `MinPay(currency: str, period: str, amount: float)`.
  - `load_profile(path: Path) -> Profile`.
  - `apply_hard_filters(lead: Lead, profile: Profile) -> str|None` — returns reason or `None`. Order: blocked company (`"blocked company: <name>"`), blocked keyword (`"blocked keyword: <kw>"`), unpaid (`"unpaid"`; triggers on `unpaid|non rémunéré|bénévole|volunteer|equity only`), kind not in targets (`"kind not targeted: <kind>"`), language (`"language: <langs>"` only when `languages` non-empty and disjoint from filter list), min pay (`"below min pay"`; only when lead pay has same currency+period as a `MinPay` and `pay.max` known and `< amount`).
- `profile.example.yaml`: real starting profile for the owner — skills (Go, C++, Java/Spring, C#/.NET, TypeScript/Next.js, Python, DevOps/Docker/K8s, systems/NUMA), and project write-ups (2–4 sentences each) for: room-mapping/packing engine, SRV orchestration engine, Furrballs/REMARC, BoosterBC Go supplier connectors, DataMart, Hubris Engine, stepwise. Targets: all six kinds; regions `["remote", "tunisia", "france", "germany", "eu", "worldwide"]`.

- [ ] **Step 1: Write failing tests** — `test_load_example_profile` (loads `profile.example.yaml`, ≥ 7 projects); one test per filter reason above asserting exact reason string; `test_min_pay_ignored_for_other_currency`; `test_clean_lead_passes` → `None`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: profile and hard filters`.

---

### Task 5: Embeddings, stage-1 scoring and nightly reweighting

**Files:**
- Create: `src/prospector/rank/{embed.py,stage1.py,weights.py}`
- Test: `tests/rank/test_stage1.py`, `tests/rank/test_weights.py`, `tests/rank/test_embed_real.py` (marked `slow`)

**Interfaces:**
- Consumes: `Lead`, `Profile`, `ScoreRepo`, `FeedbackRepo`, `KV`.
- Produces:
  - `class Embedder(Protocol): def embed(self, texts: list[str], role: Literal["query","passage"]) -> np.ndarray` (L2-normalized rows, float32).
  - `FastEmbedder(model: str, cache_dir: Path)` — prefixes `"query: "` / `"passage: "`. If `model` not in `TextEmbedding.list_supported_models()`, fall back to `"intfloat/multilingual-e5-large"` and log a warning.
  - `lead_text(lead: Lead) -> str` = `f"{title}\n{company}\n{body[:2000]}"`.
  - `profile_vectors(profile, embedder) -> np.ndarray` — one row per project write-up + one row for joined skills (role `"query"`).
  - `@dataclass Weights(sim=0.40, keywords=0.20, pay=0.10, remote=0.10, freshness=0.10, feedback=0.10)`; `Weights.load(kv) / .save(kv)` under key `"weights"`.
  - `score_stage1(lead, lead_vec, profile_vecs, pos_vecs, neg_vecs, profile, weights, now) -> tuple[float, dict[str, float]]`. Components (each in [0,1]):
    - `sim = clamp((max_cos - 0.75) / (0.90 - 0.75))`
    - `keywords = clamp(sum(w for kw,w in boost_keywords if kw.lower() in text.lower()) / 3)`
    - `pay = 1.0` if pay known and passes min-pay, `0.5` if unknown
    - `remote = 1.0` YES, `0.6` HYBRID, `0.5` UNKNOWN, NO → `1.0` if any `lead.locations` matches a target region else `0.2`
    - `freshness = exp(-age_days / 14)` (`posted_at` missing → `0.5`)
    - `feedback = clamp(0.5 + (max_cos(pos) - max_cos(neg)) / 2)`; `0.5` when both sets empty
    - final `= clamp(Σ weight·component)`; breakdown holds every component plus `"final"`.
  - `reweight(weights: Weights, rows: list[tuple[dict, bool]]) -> Weights` — `rows` = (breakdown, is_positive). Skip if `< 10` rows. For each component: `diff = mean(pos) - mean(neg)`; `w += 0.02 * sign(diff)`; clamp each to `[0.05, 0.60]`; renormalize to sum 1.

- [ ] **Step 1: Write failing tests** with a `FakeEmbedder` (deterministic hash → unit vector; identical text → identical vector):
  - `test_matching_lead_scores_higher` — lead whose text equals a project write-up beats an unrelated lead.
  - `test_breakdown_has_all_components` — keys `{sim,keywords,pay,remote,freshness,feedback,final}`.
  - `test_feedback_neutral_without_examples` → `0.5`.
  - `test_dismissed_neighbour_lowers_score`.
  - `test_reweight_noop_below_10_rows`; `test_reweight_moves_toward_positive_component_and_sums_to_one`.
  - `test_fastembed_real` (`@pytest.mark.slow`): real model embeds `["Go backend engineer"]` → shape `(1, 768)` (or 1024 on fallback), norm ≈ 1.
- [ ] **Step 2:** Run `uv run pytest tests/rank -q -m "not slow"` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest tests/rank -q` (including slow, downloads model once) → PASS.
- [ ] **Step 5:** Commit `feat: stage-1 ranking and feedback reweighting`.

---

### Task 6: LLM client and stage-2 review

**Files:**
- Create: `src/prospector/llm/client.py`, `src/prospector/rank/stage2.py`
- Test: `tests/llm/test_client.py`, `tests/rank/test_stage2.py`

**Interfaces:**
- Consumes: `Settings`, `Lead`, `Profile`, `ScoreRepo`, `KV`, `LeadRepo`.
- Produces:
  - `class LLMError(Exception)`.
  - `LLMClient(base_url: str, api_key: str, model: str, http: httpx.Client)`: `complete(system: str, user: str, session_id: str) -> str` (POST `{base_url}/chat/completions`, `temperature=0`, headers `Authorization: Bearer`, `User-Agent: prospector/<version>`, `x-opencode-session: <session_id>`); `list_models() -> list[str]` (GET `{base_url}/models`; the spec's model list endpoint is `https://opencode.ai/inference/go/v1/models` — try `{base_url}/models` first, then that URL).
  - `extract_json(text: str) -> dict` — strips ```` ``` ````/```` ```json ```` fences, else takes the substring from first `{` to last `}`; raises `ValueError`.
  - Pydantic `Stage2Result(verdict: Literal["strong","maybe","weak"], fit_summary: str, lead_with_project: str|None, red_flags: list[str], pay_estimate: str|None)`.
  - `review(lead, profile, client, kv, session_id) -> Stage2Result|None` — cache key `"llm:" + lead.content_hash` in KV; on invalid JSON/validation error send one repair prompt ("Return only valid JSON matching this schema: …" + previous reply); second failure → `None`. `LLMError` → `None`.
  - `run_stage2(leads: LeadRepo, scores: ScoreRepo, kv: KV, client, profile, cap: int, threshold: float, today: date) -> int` — calls used today tracked in KV key `f"llm_calls:{today}"`; session id `f"prospector-{today}"`; stops at cap; returns number reviewed.
- System prompt (exact): `"You screen job and gig leads for one candidate. Answer ONLY with JSON: {\"verdict\": \"strong|maybe|weak\", \"fit_summary\": \"<=2 sentences\", \"lead_with_project\": \"<project name or null>\", \"red_flags\": [\"...\"], \"pay_estimate\": \"<string or null>\"}"`. User prompt: candidate skills + project names/write-ups, then the lead (title, company, location, pay text, first 3000 chars of body).

- [ ] **Step 1: Write failing tests** (respx mocks the HTTP endpoint):
  - `test_complete_sends_headers` — asserts `x-opencode-session` and `User-Agent` on the request.
  - `test_extract_json_handles_fences_and_prose` — ```` "```json\n{\"a\":1}\n```" ```` → `{"a":1}`; `"Sure! {\"a\":1} hope this helps"` → `{"a":1}`.
  - `test_review_repairs_once_then_succeeds` — first reply prose, second valid JSON → result; exactly 2 calls.
  - `test_review_returns_none_after_failed_repair` — 2 calls, `None`.
  - `test_review_uses_cache` — second `review` of same lead makes 0 HTTP calls.
  - `test_run_stage2_respects_daily_cap` — 30 eligible leads, cap 20 → 20 reviewed; second run same day → 0.
  - `test_http_error_leaves_lead_unreviewed` — 503 → `review` returns `None`, `run_stage2` continues to next lead.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: LLM client and stage-2 review`.

---

### Task 7: Source framework, runner and health

**Files:**
- Create: `src/prospector/sources/{base.py,runner.py,registry.py,robots.py}`
- Test: `tests/sources/test_runner.py`, `tests/sources/test_robots.py`

**Interfaces:**
- Produces:
  - `class Source(Protocol)`: attributes `id: str`, `interval_hours: float`; method `fetch(self, http: httpx.Client) -> list[RawLead]`.
  - `run_source(source: Source, http: httpx.Client, health: HealthRepo, now: datetime) -> list[RawLead]` — on exception: `record_failure`; if `consecutive_failures >= 3` → `set_paused(True)`; returns `[]`. On success: `drift = len(leads) == 0 or missing_ratio(leads) > 0.5` where missing = empty `title`, `url` or `body`; `record_success(..., drift)`; unpauses.
  - `should_run(h: SourceHealth, source: Source, now: datetime) -> bool` — paused → only if `now - last_run >= 24h`; else `now - last_run >= interval_hours`.
  - `robots_allowed(url: str, http: httpx.Client, user_agent: str) -> bool` (urllib.robotparser; robots fetch failure → `False`).
  - `build_sources(settings: Settings, mail: MailRepo) -> list[Source]` (`mail` is passed to `AlertsSource`) — maps ids `remotive, remoteok, himalayas, arbeitnow, adzuna, hn, github_bounties, freelancer, keejob, alerts` to classes; only `settings.enabled_sources`; sources lacking required credentials (adzuna, github_bounties) are skipped with a warning.

- [ ] **Step 1: Write failing tests** — `test_exception_records_failure_and_pauses_after_three`, `test_success_resets_and_unpauses`, `test_zero_leads_flags_drift`, `test_half_missing_fields_flags_drift`, `test_should_run_paused_waits_24h`, `test_robots_disallow` (respx serves `Disallow: /jobs`), `test_robots_fetch_failure_denies`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: source framework with health and drift detection`.

---

### Task 8: API adapters — Remotive, RemoteOK, Himalayas, Arbeitnow

**Files:**
- Create: `src/prospector/sources/{remotive.py,remoteok.py,himalayas.py,arbeitnow.py}`
- Fixtures: `tests/fixtures/{remotive,remoteok,himalayas,arbeitnow}/sample.json`
- Test: `tests/sources/test_job_apis.py`

**Interfaces:**
- Consumes: `Source` protocol, `RawLead`.
- Produces classes `Remotive`, `RemoteOK`, `Himalayas`, `Arbeitnow`, each with `id` equal to its registry key and `interval_hours`: Remotive 4, RemoteOK 4, Himalayas 6, Arbeitnow 6.
- Endpoints: Remotive `https://remotive.com/api/remote-jobs?category=software-dev`; RemoteOK `https://remoteok.com/api` (skip element 0, the legal notice; keep the original job URL as `url` to satisfy their attribution requirement); Himalayas `https://himalayas.app/jobs/api?limit=100`; Arbeitnow `https://www.arbeitnow.com/api/job-board-api`.

- [ ] **Step 1:** Record fixtures: fetch each endpoint once, keep the first 5 jobs, save to `sample.json` (for RemoteOK keep element 0 too).
- [ ] **Step 2: Write failing tests** (respx serves fixtures): for each adapter `test_<id>_maps_fields` — returns 5 leads, every lead has non-empty `title`, `url`, `body`, `source_id == id`, `external_id` unique; RemoteOK returns 5 (legal notice skipped).
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement. **Step 5:** Run → PASS.
- [ ] **Step 6:** Commit `feat: remote job board adapters`.

---

### Task 9: API adapters — Adzuna, HN "Who is hiring", GitHub bounties, Freelancer

**Files:**
- Create: `src/prospector/sources/{adzuna.py,hn.py,github_bounties.py,freelancer.py}`
- Fixtures: `tests/fixtures/{adzuna,hn,github_bounties,freelancer}/*.json`
- Test: `tests/sources/test_other_apis.py`

**Interfaces:**
- `Adzuna(app_id, app_key, countries=("fr","de","gb","au"), what="software developer")`, interval 6 h — `https://api.adzuna.com/v1/api/jobs/{country}/search/1?app_id=…&app_key=…&what=…&results_per_page=50&content-type=application/json`; `location_text` includes the country code.
- `HackerNewsHiring()`, interval 6 h — find latest story via `https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&query=hiring`, then `https://hn.algolia.com/api/v1/items/{id}`; one lead per top-level comment; `title` = first line of comment text (≤ 120 chars); `url = https://news.ycombinator.com/item?id=<comment id>`; `company` = text before first `|` if present.
- `GitHubBounties(token)`, interval 4 h — `GET https://api.github.com/search/issues?q=label:"💎 Bounty" state:open&sort=created&per_page=50`; `kind_hint=Kind.BOUNTY`; `pay_text` from a `$<number>` in labels or title.
- `Freelancer()`, interval 3 h — `GET https://www.freelancer.com/api/projects/0.1/projects/active/?query=<q>&limit=50&full_description=true` for queries `["golang","c++","spring boot","next.js","devops"]`; `kind_hint=Kind.GIG`; `url = https://www.freelancer.com/projects/<seo_url>`; `pay_text` from `budget.minimum`–`budget.maximum` + `currency.code`.

- [ ] **Step 1:** Record fixtures (owner-provided Adzuna/GitHub credentials, or skip recording and hand-write a minimal fixture matching the documented response shape if credentials are not yet available).
- [ ] **Step 2: Write failing tests** — `test_adzuna_maps_fields_per_country` (2 countries → leads tagged with each), `test_hn_one_lead_per_top_level_comment` (child replies ignored, deleted comments skipped), `test_github_bounty_kind_and_pay`, `test_freelancer_budget_to_pay_text`.
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement. **Step 5:** Run → PASS.
- [ ] **Step 6:** Commit `feat: adzuna, HN, GitHub bounty and freelancer adapters`.

---

### Task 10: Mail ingest endpoint and alerts adapter

**Files:**
- Create: `src/prospector/web/ingest.py`, `src/prospector/sources/alerts/{__init__.py,parse.py,generic.py}`
- Fixtures: `tests/fixtures/alerts/{confirm_fr.eml,unknown_sender.eml,html_only_latin1.eml,generic_jobs.eml}`
- Test: `tests/web/test_ingest.py`, `tests/sources/test_alerts.py`

**Interfaces:**
- Consumes: `MailRepo`, `Settings.bridge_secret`.
- Produces:
  - `sign(secret: bytes, timestamp: str, body: bytes) -> str` = hex HMAC-SHA256 of `timestamp.encode() + b"." + body` (in `web/ingest.py`; the Worker implements the same).
  - `router = APIRouter()` with `POST /ingest/mail`: headers `X-Prospector-Timestamp`, `X-Prospector-Signature: sha256=<hex>`; responses: body > 5 MB → 413; bad/missing signature or timestamp outside ±300 s → 401; else `MailRepo.insert` → 202 `{"id": n}`.
  - `parse_alert(raw: bytes) -> AlertResult` with `AlertResult(leads: list[RawLead], confirmation_url: str|None, parsed: bool)`. Uses `email.message_from_bytes(raw, policy=email.policy.default)`; per-sender parser registry `PARSERS: dict[str, Callable[[EmailMessage], list[RawLead]]]` keyed by sender domain (empty in v1 except tests; filled in Task 17). Confirmation: subject or body matches `confirm|verify|confirmez|vérifiez|activate|activer` and contains a link → `confirmation_url` = first such link. Unknown sender → `generic.extract(msg)`: links whose anchor text is ≥ 4 words and whose URL path contains `job|emploi|offre|career|position|vacanc` become `RawLead(source_id="alerts", ...)`; zero results → `parsed=False`.
  - `AlertsSource` (`id="alerts"`, interval 0.25 h): `fetch` reads `MailRepo.pending()` (constructed with a `MailRepo`), parses each, marks `parsed` / `confirmation` (with url) / `unparsed` (note = sender + subject); any exception for one message → mark `unparsed` with the error and continue.

- [ ] **Step 1:** Hand-write the four `.eml` fixtures (`html_only_latin1.eml` declares `charset=iso-8859-1` with é characters and no text part).
- [ ] **Step 2: Write failing tests** — `test_ingest_accepts_valid_signature` (202), `test_ingest_rejects_bad_signature` (401), `test_ingest_rejects_stale_timestamp` (401 at +301 s), `test_ingest_rejects_oversize` (413), `test_confirmation_detected` (url extracted, no leads), `test_unknown_sender_generic_links`, `test_unknown_sender_no_links_is_unparsed`, `test_html_only_latin1_does_not_crash`, `test_one_bad_message_does_not_stop_others` (monkeypatch parser to raise for one message).
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement. **Step 5:** Run → PASS.
- [ ] **Step 6:** Commit `feat: signed mail ingest and alerts adapter`.

---

### Task 11: Keejob scraper (Tunisia)

**Files:**
- Create: `src/prospector/sources/keejob.py`
- Fixtures: `tests/fixtures/keejob/list.html`
- Test: `tests/sources/test_keejob.py`

**Interfaces:**
- `Keejob()`, `id="keejob"`, interval 24 h. Before fetching, `robots_allowed(listing_url, ...)`; if `False`, return `[]` and log (counts as drift, which is visible on the health page).

- [ ] **Step 1:** Manually check `https://www.keejob.com/robots.txt` and the site's terms. **If scraping job listings is disallowed, stop this task:** remove `keejob` from the registry, note it in `README.md` under "Sources not used", and commit `docs: note keejob excluded (robots/terms)`. Otherwise continue.
- [ ] **Step 2:** Save one listing page of IT offers as `list.html`; identify CSS selectors for title, company, location, link, date.
- [ ] **Step 3: Write failing tests** — `test_keejob_parses_listing` (≥ 5 leads with title/url/company, `location_text` contains a Tunisian city), `test_keejob_respects_robots` (respx robots disallow → `[]`, listing URL never requested).
- [ ] **Step 4:** Run → FAIL. **Step 5:** Implement with selectolax. **Step 6:** Run → PASS.
- [ ] **Step 7:** Commit `feat: keejob scraper`.

---

### Task 12: Auth and dashboard

**Files:**
- Create: `src/prospector/web/{app.py,auth.py,dashboard.py}`, `src/prospector/web/templates/{base.html,list.html,_row.html,detail.html,health.html}`, `src/prospector/web/static/{htmx.min.js,app.css}`
- Test: `tests/web/test_auth.py`, `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: all repos, `ingest.router`.
- Produces:
  - `AccessVerifier(team_domain: str, aud: str, http: httpx.Client)`: `verify(token: str) -> dict` (RS256 against `https://<team_domain>/cdn-cgi/access/certs`, keys cached 1 h, checks `aud` and `exp`; raises `PermissionError`).
  - `access_middleware` — `/healthz` exempt; client IP in `100.64.0.0/10` → allowed; else requires valid `Cf-Access-Jwt-Assertion` → else 403.
  - `create_app(ctx: AppContext) -> FastAPI` where `AppContext(settings, conn, repos..., verifier)`; mounts static, ingest router, dashboard routes, `/healthz` → `"ok"`.
  - Routes: `GET /?tab=new|starred|applied|filtered&kind=&remote=&source=&min_score=&sort=score|date&page=`; `GET /lead/{id}`; `POST /lead/{id}/{action}` (`star|dismiss|applied|reset`; updates status via `LeadRepo.set_status` + `FeedbackRepo.record`; returns `_row.html` for HTMX swap); `GET /health` (sources table: last run, last ok, count, failures, paused, drift, last error); `POST /needs-you/{id}/dismiss`. The list page shows the "Needs you" panel (confirmation links as plain links the owner clicks, unparsed mails, paused sources).
- Detail page shows normalized fields, stage-1 breakdown table, stage-2 verdict/summary/project/red flags (or "unreviewed"), original link, all sources.

- [ ] **Step 1: Write failing tests** (FastAPI `TestClient`; set `client=("100.100.1.1", 1234)` for tailnet, `("172.17.0.1", 1234)` for non-tailnet; `AccessVerifier` built with a test RSA key and respx-served certs):
  - `test_tailnet_allowed_without_jwt`, `test_non_tailnet_without_jwt_forbidden`, `test_valid_jwt_allowed`, `test_wrong_aud_forbidden`, `test_healthz_exempt`.
  - `test_list_tabs` — starred lead appears only in the starred tab.
  - `test_star_action_returns_row_and_records_feedback`.
  - `test_detail_shows_unreviewed_when_no_stage2`.
  - `test_health_page_lists_paused_source`.
  - `test_needs_you_shows_confirmation_link` (rendered as `<a href=…>`; no server-side fetch of that URL — assert respx saw no request to it).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; vendor `htmx.org@2.0.4/dist/htmx.min.js`. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: access-checked dashboard`.

---

### Task 13: Digest (Telegram + email)

**Files:**
- Create: `src/prospector/notify/{digest.py,telegram.py,email.py,run.py}`
- Test: `tests/notify/test_digest.py`

**Interfaces:**
- Consumes: `LeadRepo.new_since`, `LeadRepo.starred_with_deadline_within`, `HealthRepo.all`, `KV`.
- Produces:
  - `Digest(items: list[LeadRow], deadlines: list[LeadRow], warnings: list[str], dashboard_url: str)`.
  - `build_digest(leads, health, kv, now, dashboard_url) -> Digest` — `items = new_since(kv["last_digest_at"] or now-24h, limit=10)`; `deadlines = starred_with_deadline_within(3, today)`; warnings: one per paused source (`"<id> paused: <last_error>"`) and per drifting source (`"<id> returned suspicious results"`).
  - `render_telegram(d: Digest) -> list[str]` — HTML parse mode, every dynamic string `html.escape`d, each line `"<b>{score:.2f}</b> {title} — {company} · {kind}{' · ★ '+verdict if stage2}\n{dashboard_url}/lead/{id}"`; split on line boundaries so each message ≤ 4096 chars.
  - `render_email(d: Digest) -> tuple[str, str, str]` — `(subject, text, html)`; subject `f"Prospector: {len(items)} new leads"`.
  - `send_telegram(http, token, chat_id, text)`; `send_email_via_bridge(http, bridge_url, secret, subject, text, html)` — POST `{bridge_url}/digest` with JSON body and the same timestamp+signature headers as ingest (`sign` from Task 10).
  - `send_digest(ctx, now) -> None` — sends Telegram (all chunks) and email independently. If Telegram fails, email body gets a first line `"⚠ Telegram delivery failed: <error>"`; if email fails after Telegram succeeded, send one extra Telegram message `"⚠ Email digest failed: <error>"`. Set `kv["last_digest_at"] = now` if at least one channel succeeded.

- [ ] **Step 1: Write failing tests** — `test_digest_top10_since_last`, `test_deadline_section`, `test_warnings_for_paused_and_drift`, `test_telegram_escapes_html` (title `"C++ <Senior> & Lead"` → `&lt;Senior&gt; &amp;`), `test_telegram_splits_over_4096` (40 long items → every chunk ≤ 4096, all items present), `test_email_failure_reported_on_telegram`, `test_telegram_failure_noted_in_email`, `test_last_digest_not_advanced_when_both_fail`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: telegram and email digest`.

---

### Task 14: Pipeline, scheduler, nightly jobs and CLI

**Files:**
- Create: `src/prospector/pipeline.py`, `src/prospector/scheduler.py`, `src/prospector/__main__.py`
- Test: `tests/test_pipeline.py`, `tests/test_scheduler.py`, `tests/test_e2e_smoke.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `ingest(ctx, source: Source, now) -> IngestStats(fetched, new, merged, filtered)` — `run_source` → `normalize` → if `by_canonical_url` or `is_duplicate` against `recent_by_company(company_norm)` → `add_source` (merged); else `insert`, `put_raw`, `apply_hard_filters` (→ `set_status(FILTERED, reason)`), else embed (`role="passage"`), `save_embedding`, `score_stage1`, `save_stage1`.
  - `stage2(ctx, today) -> int` → `run_stage2` with settings cap/threshold.
  - `nightly(ctx, now)` — `reweight` using breakdowns of feedback leads, `prune_raw(30)`, backup via `conn.backup()` to `data_dir/backups/prospector-YYYYMMDD.db`, delete backups older than 14 days.
  - `build_scheduler(ctx) -> BackgroundScheduler` (`timezone=ZoneInfo("Africa/Tunis")`): one tick job every 15 min that runs each source where `should_run` is true, then `stage2`; `CronTrigger(hour=8, minute=0)` → `send_digest`; `CronTrigger(hour=3, minute=0)` → `nightly`; jobs use `max_instances=1, coalesce=True`.
  - `select_model(client: LLMClient, primary: str, fallback: str) -> str|None` — called once at `serve` startup: returns `primary` if listed by `list_models()`, else `fallback` (warning logged), else `None` (stage 2 disabled, error logged, digest warning `"LLM model unavailable"`); `list_models()` failure → keep `primary` and warn.
  - CLI `python -m prospector`: `serve` (uvicorn `create_app`, runs `select_model`, starts scheduler in lifespan, host/port from `HOST`/`PORT` env, default `0.0.0.0:8080` inside the container), `run-source <id>`, `stage2`, `digest [--dry-run]` (prints Telegram chunks), `check-llm` (prints `list_models()` and whether configured models exist).
- [ ] **Step 1: Write failing tests**
  - `test_ingest_new_merged_filtered` — fake source returns 3 leads: one new, one duplicate of an existing lead (different source), one blocked keyword → stats `(3, 1, 1, 1)`.
  - `test_digest_job_runs_at_8_tunis` — inspect scheduler: digest trigger `get_next_fire_time(None, datetime(2026,11,3,6,0,tzinfo=UTC))` == `2026-11-03 07:00 UTC` (08:00 Africa/Tunis, UTC+1, no DST).
  - `test_nightly_backup_and_retention` — 16 old backup files → 14 remain after run, new one created.
  - `test_select_model_falls_back` — models list lacks `glm-5.3-flash` but has `qwen3.8-flash` → returns `"qwen3.8-flash"`; neither present → `None`.
  - `test_e2e_smoke` — temp data dir, fake sources + `FakeEmbedder` + respx LLM: run tick → stage2 → `digest --dry-run`; assert ≥ 1 digest chunk and `GET /` (tailnet client) returns 200 containing a lead title.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** `uv run pytest -q -m "not slow"` → all PASS.
- [ ] **Step 5:** Commit `feat: pipeline, scheduler and CLI`.

---

### Task 15: mail-bridge Cloudflare Worker

**Files:**
- Create: `mail-bridge/{package.json,tsconfig.json,wrangler.jsonc,vitest.config.ts,src/index.ts,src/sign.ts,test/index.spec.ts}`

**Interfaces:**
- Bindings (`wrangler.jsonc`): `send_email` binding `DIGEST_EMAIL` with `destination_address` = owner's Zoho address (var placeholder `OWNER_EMAIL`); R2 bucket `SPOOL` (`mail-bridge-spool`); Queue producer+consumer `RETRY_QUEUE` (`mail-bridge-retry`, `max_retries: 150`, `max_batch_size: 1`); vars `INGEST_URL=https://prospector.thesphynx.net/ingest/mail`, `FROM_ADDRESS=digest@prospector.thesphynx.net`; secrets `BRIDGE_SECRET`, `ACCESS_CLIENT_ID`, `ACCESS_CLIENT_SECRET`.
- `sign(secret, timestamp, body: Uint8Array): Promise<string>` — byte-identical to the Python `sign` (Web Crypto HMAC-SHA256, hex).
- `email(message, env, ctx)` — read `message.raw` fully; POST to `INGEST_URL` with `CF-Access-Client-Id`, `CF-Access-Client-Secret`, `X-Prospector-Timestamp`, `X-Prospector-Signature`; on non-2xx or throw → `SPOOL.put(key, raw)` and `RETRY_QUEUE.send({key, receivedAt})` (raw MIME can exceed the 128 KB queue message limit, hence R2).
- `queue(batch, env)` — for each message: if `now - receivedAt > 24h` → delete R2 object, `console.error`, `ack`; else re-POST; success → delete R2 object + `ack`; failure → `retry({delaySeconds: 600})`.
- `fetch(request, env)` — only `POST /digest`; verify signature (±300 s) else 401; body `{subject, text, html}` → build MIME with `mimetext` (`From: FROM_ADDRESS`, `To: OWNER_EMAIL`) → `DIGEST_EMAIL.send(new EmailMessage(...))` → 202.

- [ ] **Step 1:** `npm create cloudflare@latest mail-bridge -- --type hello-world --lang ts --no-deploy --no-git`; add `mimetext`, `@cloudflare/vitest-pool-workers`, `vitest`.
- [ ] **Step 2: Write failing tests** (`test/index.spec.ts`) — `sign matches python vector` (fixed secret `"s"`, timestamp `"1700000000"`, body `"hello"` → the hex produced by Python `sign(b"s","1700000000",b"hello")`, computed once and pasted in both test suites); `email forwards with signature headers` (mock `fetch`); `email spools to R2 and queues on 503`; `queue drops after 24h`; `queue retries on failure`; `digest rejects bad signature` (401); `digest sends email` (mock `DIGEST_EMAIL.send` called once).
- [ ] **Step 3:** `npx vitest run` → FAIL. **Step 4:** Implement. **Step 5:** `npx vitest run` → PASS; `npx tsc --noEmit` clean.
- [ ] **Step 6:** Add the same vector test to `tests/web/test_ingest.py` (`test_sign_cross_language_vector`) and run `uv run pytest tests/web -q` → PASS.
- [ ] **Step 7:** Commit `feat: mail-bridge worker`.

---

### Task 16: Packaging, deployment and owner setup docs

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `README.md`, `deploy/cloudflared-ingress.yml.example`
- Modify: `.env.example` (final variable list)

**Interfaces:**
- `Dockerfile`: `python:3.12-slim`, uv sync `--frozen --no-dev`, non-root user, `CMD ["python","-m","prospector","serve"]`, `HEALTHCHECK` curls `/healthz`.
- `docker-compose.yml`: service `prospector`, `env_file: .env`, volume `./data:/data`, `mem_limit: 3g`, `restart: unless-stopped`, `TZ=Africa/Tunis`, ports `127.0.0.1:8080:8080` and `${TAILSCALE_IP}:8080:8080`.
- `deploy/cloudflared-ingress.yml.example`: ingress rule `prospector.thesphynx.net → http://localhost:8080`.
- `README.md`: what it is, local dev commands, deploy command (`git pull && docker compose up -d --build` over Tailscale SSH), and the owner setup checklist from spec §12 (OpenCode Go key, BotFather + chat id, Adzuna keys, GitHub token, Email Routing on the subdomain + verify Zoho destination, Access apps: dashboard = owner identity, `/ingest/mail` = service token, `wrangler deploy` + secrets, subscribe alerts to `alerts@prospector.thesphynx.net`), plus a "Sources not used" section.

- [ ] **Step 1:** Write files. `docker build -t prospector .` → succeeds.
- [ ] **Step 2:** `docker compose up -d` locally with a test `.env` (`TAILSCALE_IP=127.0.0.2` or the dev machine's tailnet IP) → `curl -s localhost:8080/healthz` prints `ok`; `curl -s -o /dev/null -w "%{http_code}" localhost:8080/` prints `403` (localhost through docker proxy is not tailnet → needs JWT).
- [ ] **Step 3:** `docker stats --no-stream prospector` after first model load shows memory < 3 GB.
- [ ] **Step 4:** Commit `chore: docker packaging and setup docs`.
- [ ] **Step 5 (with owner, on the server over Tailscale):** deploy, add cloudflared ingress, then verify: from a tailnet device `/` returns 200; from the public hostname without Access login, Cloudflare blocks; `python -m prospector check-llm` lists the configured model; `python -m prospector run-source remotive` inserts leads; `python -m prospector digest` delivers both a Telegram message and an email; sending a test email to `alerts@prospector.thesphynx.net` creates a mail row (dashboard "Needs you" or new leads).

---

### Task 17: Per-site alert parsers (after real alerts arrive)

**Prerequisite:** the owner has subscribed alerts (spec §12) and at least one real alert email per site has been received.

**Files:**
- Create: `src/prospector/sources/alerts/{linkedin.py,indeed.py,wttj.py,malt.py,tanitjobs.py}` (only for sites with a received sample)
- Fixtures: `tests/fixtures/alerts/<site>.eml` (redact the owner's name/email and personal tracking tokens)
- Modify: `src/prospector/sources/alerts/parse.py` (`PARSERS` registry)
- Test: `tests/sources/test_alert_sites.py`

- [ ] **Step 1:** Export one received alert per site from the stored raw mails (`MailRepo`) into a redacted fixture.
- [ ] **Step 2: Write failing tests** — `test_<site>_alert_extracts_jobs`: expected count equals the number of job cards visible in the email; each lead has title, company, canonical URL without tracking params.
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement each parser `parse(msg: EmailMessage) -> list[RawLead]` and register it by sender domain. **Step 5:** Run → PASS.
- [ ] **Step 6:** Commit `feat: per-site alert parsers`.
