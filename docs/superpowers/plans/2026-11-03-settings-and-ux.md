# Settings Page and UX Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure Prospector (keys, tuning, profile, quick tests) from the dashboard, and make the dashboard faster to work through.

**Architecture:** Overrides in `DATA_DIR/settings.json` are passed as keyword arguments to `Settings(...)`. pydantic-settings gives keyword arguments priority over env and `.env`, so every existing reader is unchanged. A save validates the merged settings, writes the file, and restarts the process; Docker brings the app back up. Restarting and background jobs are injectable `AppContext` callables, so tests stay synchronous. UX work is templates plus one vanilla `static/app.js`.

**Tech Stack:** existing (FastAPI, Jinja2, HTMX 2.0.4, pydantic-settings, APScheduler 3, SQLite). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-03-settings-and-ux-design.md`

## Global Constraints

- Secrets (`llm_api_key`, `telegram_token`, `bridge_secret`, `adzuna_app_key`, `github_token`) never appear in any HTML response, log line or error text. The one exception is `POST /settings/reveal-bridge-secret`, which returns `bridge_secret` with `Cache-Control: no-store`.
- Editable allow-list (spec §2): `llm_api_key, llm_base_url, telegram_token, telegram_chat_id, bridge_url, bridge_secret, access_team_domain, access_aud, adzuna_app_id, adzuna_app_key, github_token, dashboard_url, llm_model, llm_fallback_model, llm_daily_cap, stage2_threshold, enabled_sources, digest_time`. Any other posted key is ignored.
- Ranges: `llm_daily_cap` 1–500; `stage2_threshold` 0–1; `digest_time` is `HH:MM` (Africa/Tunis, default `08:00`); `enabled_sources` contains only ids registered in `sources.registry.FACTORIES`.
- `settings.json` is written atomically (temp file + `os.replace`), mode `0600`. A broken file is renamed `settings.json.rejected`; the app then starts from env and shows the banner "Your saved settings were ignored: <reason>".
- Every non-GET request except `/ingest/mail` gets 403 when `Sec-Fetch-Site` is present and not `same-origin`, or when `Origin` is present and its host is not the request's `Host`.
- Restart: the response is sent first; then a thread sleeps 1 s and calls `os._exit(0)`. The restarting page polls `/healthz` every 2 s and gives up with a message after 90 s.
- Errors from test buttons go through `prospector.http.describe_error` or `str(LLMError)`, which never contain URLs.
- Run tests with `C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe -m uv run pytest -q -m "not slow"`.

## Review Focus

1. A save that leaves a secret input empty must keep the stored secret and not clear it. Test: `test_empty_secret_keeps_value` (Task 3).
2. Non-numeric or out-of-range numbers (`llm_daily_cap=abc`, `stage2_threshold=2`) re-render with a field error (status 400, nothing written), never a 500. Test: `test_bad_number_is_field_error` (Task 3).
3. A profile with zero projects must save, and re-scoring must not crash (sim simply becomes 0). Test: `test_rescore_with_no_projects` (Task 5).
4. A settings file holding a key that is no longer editable (or is unknown) must be ignored, not crash startup. Test: `test_unknown_override_key_ignored` (Task 1).
5. Undo when the feedback row is already gone (double-click) is a no-op 200 that still restores the status. Test: `test_undo_twice` (Task 8).

---

### Task 1: Settings overrides store

**Files:**
- Modify: `src/prospector/config.py` (add `digest_time: str = "08:00"` with a validator for `^([01]\d|2[0-3]):[0-5]\d$`; add `EDITABLE: tuple[str, ...]` and `SECRETS: frozenset[str]` from Global Constraints)
- Create: `src/prospector/settings_store.py`
- Modify: `src/prospector/__main__.py` (`main()` builds settings through `load_settings()`; keep `check_secrets`)
- Test: `tests/test_settings_store.py`

**Interfaces:**
- Produces:
  - `@dataclass class LoadedSettings: settings: Settings; overrides: dict[str, Any]; origins: dict[str, Literal["override","env","default"]]; rejected: str | None`
  - `load_settings(env_file: str | None = ".env") -> LoadedSettings`. Builds env-only `Settings(_env_file=env_file)`, reads `settings.data_dir / "settings.json"`, keeps only `EDITABLE` keys, and builds `Settings(_env_file=env_file, **overrides)`. If parsing or validation fails, it renames the file to `.rejected` and returns the env-only settings with `rejected=<reason>`. A field's origin is `override` if it is in the overrides, `env` if it is in the env-only model's `model_fields_set`, and `default` otherwise.
  - `validate_overrides(env_file: str | None, overrides: dict) -> tuple[Settings | None, dict[str, str]]`. Returns `(settings, {})` or `(None, {field: message})`. It also enforces `len(bridge_secret) >= 32` and the `enabled_sources` ids.
  - `save_overrides(data_dir: Path, overrides: dict) -> None` (atomic, `0600`).

- [ ] **Step 1: Write failing tests** in `tests/test_settings_store.py`. Use `tmp_path` as `DATA_DIR`, with `monkeypatch.setenv` for `DATA_DIR`, `PROFILE_PATH`, `LLM_API_KEY=envkey`, `BRIDGE_SECRET="e"*32`, `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, and `env_file=None`:
  - `test_override_beats_env`: write `{"llm_api_key": "uikey", "llm_daily_cap": 5}`. `settings.llm_api_key.get_secret_value() == "uikey"`, `llm_daily_cap == 5`, `origins["llm_api_key"] == "override"`, `origins["access_aud"] == "env"`, `origins["stage2_threshold"] == "default"`.
  - `test_no_file_is_env_only`: `overrides == {}` and `rejected is None`.
  - `test_unknown_override_key_ignored`: `{"data_dir": "/x", "bogus": 1, "llm_model": "m"}` gives `settings.data_dir == tmp_path`, `llm_model == "m"`, and `rejected is None`.
  - `test_corrupt_file_rejected`: the file contains `"{not json"`. `rejected` is truthy, `(tmp_path/"settings.json.rejected").exists()`, and settings come from env.
  - `test_invalid_value_rejected`: `{"llm_daily_cap": "abc"}` gives `rejected` mentioning `llm_daily_cap`.
  - `test_validate_overrides_errors`: `{"stage2_threshold": 2, "bridge_secret": "short", "enabled_sources": ["nope"], "digest_time": "25:00"}` gives four error keys.
  - `test_save_atomic_and_private`: after `save_overrides`, `json.loads` round-trips, and on POSIX `stat().st_mode & 0o777 == 0o600` (skip on Windows).
- [ ] **Step 2: Run them.** Expected: FAIL with `ModuleNotFoundError: prospector.settings_store`.
- [ ] **Step 3: Implement** `config.py` additions and `settings_store.py` per Interfaces. Catch `json.JSONDecodeError`, `OSError` and `pydantic.ValidationError` in `load_settings`, and log the reason without values.
- [ ] **Step 4: Run them, then the full suite.** Expected: all PASS.
- [ ] **Step 5: Commit** `feat: settings.json overrides layered over env`.

### Task 2: Same-origin check

**Files:**
- Modify: `src/prospector/web/auth.py` (add `make_same_origin_middleware()`)
- Modify: `src/prospector/web/app.py` (register it, after the access middleware runs)
- Test: `tests/web/test_same_origin.py`

**Interfaces:**
- Produces: `make_same_origin_middleware(exempt: set[str] = {"/ingest/mail"})`, which returns `PlainTextResponse("cross-origin request refused", 403)` per Global Constraints. Missing headers pass, because curl and old browsers send neither.

- [ ] **Step 1: Write failing tests** with a `TestClient` as tailnet, against `POST /lead/{id}/star`:
  - `test_cross_site_post_refused`: header `Sec-Fetch-Site: cross-site` gives 403, and the status is unchanged.
  - `test_foreign_origin_refused`: `Origin: https://evil.example` gives 403.
  - `test_same_origin_post_allowed`: `Origin: http://testserver` plus `Sec-Fetch-Site: same-origin` gives 200.
  - `test_get_not_checked`: `GET /` with `Sec-Fetch-Site: cross-site` gives 200.
  - `test_ingest_exempt`: a signed POST to `/ingest/mail` with `Origin: https://evil.example` gives 202. Reuse the signing helper from `tests/web/test_ingest.py`.
- [ ] **Step 2: Run them.** Expected: the 403 tests FAIL.
- [ ] **Step 3: Implement** the middleware. Compare `urlsplit(origin).netloc` with `request.headers["host"]`.
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): refuse cross-origin state-changing requests`.

### Task 3: Settings page — keys, connections, tuning

**Files:**
- Modify: `src/prospector/context.py` (fields `restart: Callable[[], None] = lambda: None`, `run_background: Callable[[Callable[[], None]], None] = lambda fn: fn()`, `loaded: LoadedSettings | None = None`)
- Modify: `src/prospector/__main__.py` (`cmd_serve` sets `ctx.loaded`, `ctx.restart = _restart_soon`, and `ctx.run_background = lambda fn: sched.add_job(fn)`)
- Create: `src/prospector/web/settings.py` (`make_settings_router(ctx) -> APIRouter`)
- Create: `src/prospector/web/templates/settings.html`, `src/prospector/web/templates/restarting.html`
- Modify: `src/prospector/web/templates/base.html` (Settings nav item; red banner when `request.app.state.ctx.loaded.rejected`)
- Modify: `src/prospector/web/app.py` (include the router)
- Test: `tests/web/test_settings_page.py`

**Interfaces:**
- Consumes: `LoadedSettings`, `validate_overrides`, `save_overrides`, `EDITABLE`, `SECRETS` (Task 1); `FACTORIES` (registry).
- Produces:
  - Routes:
    - `GET /settings`.
    - `POST /settings`: form fields named like the `Settings` fields; `enabled_sources` is a multi-value checkbox list; secrets also take `clear_<name>=1`.
    - `POST /settings/reset/{field}`.
    - `POST /settings/reveal-bridge-secret`.
  - A successful save or reset calls `save_overrides`, then `ctx.restart()`, and renders `restarting.html`.
  - Field error responses are status 400 and reuse `settings.html` with an `errors` dict.
  - `__main__._restart_soon() -> None` starts a daemon thread that sleeps 1 s and calls `os._exit(0)`.
  - `settings.html` sections have ids `keys`, `tuning`, `profile`, `tests`. Later tasks fill `#profile` and `#tests`; each field row has `id="f-<name>"` for checklist links.

- [ ] **Step 1: Write failing tests.** The `ctx` fixture gets `ctx.loaded = load_settings(env_file=None)` with env from monkeypatch, `restart` is a list-append spy, and every secret is set to a distinct marker such as `"SECRET-LLM-123"`.
  - `test_page_never_renders_secrets`: `GET /settings` contains none of the markers, and does contain "set".
  - `test_save_writes_override_and_restarts`: POST `llm_model=x, llm_daily_cap=30` writes `settings.json` with those values, the spy is called once, and the response contains "Restarting".
  - `test_empty_secret_keeps_value`: POST with `llm_api_key=""` leaves the file without `llm_api_key` (or with its prior override).
  - `test_clear_secret_removes_override`.
  - `test_bad_number_is_field_error`: `llm_daily_cap=abc` gives 400, the page shows an error next to `f-llm_daily_cap`, no file is written, and the spy is not called.
  - `test_unknown_field_ignored`: `data_dir=/etc` is not in the file.
  - `test_reset_drops_override`.
  - `test_reveal_bridge_secret`: returns the bridge marker, `cache-control: no-store`, and no other marker.
  - `test_origin_shown`: a field set by override shows "set here", and an env field shows "from .env".
  - `test_rejected_banner`: `ctx.loaded.rejected = "bad json"` puts "Your saved settings were ignored: bad json" on `/`.
- [ ] **Step 2: Run them.** Expected: FAIL (404 on `/settings`).
- [ ] **Step 3: Implement** the router and templates. Build the form from `EDITABLE`:
  - Secrets: `type=password`, `autocomplete=off`, empty value, placeholder "set — leave empty to keep" or "not set", plus a Clear checkbox.
  - Model inputs: `list="llm-models"`.
  - Sources: checkboxes from `FACTORIES`, marked "needs credentials" when the factory returns None for the current settings.
  - Access fields: the spec §4 note.
  - Number fields: parse with `float`/`int` inside a try. Failures go into `errors` before calling `validate_overrides`.
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): settings page with write-only secrets and restart on save`.

### Task 4: Configurable digest time

**Files:**
- Modify: `src/prospector/scheduler.py` (the digest `CronTrigger` uses `settings.digest_time`)
- Modify: `src/prospector/web/dashboard.py` (`next_digest(now, at: time)`, called with the parsed `ctx.settings.digest_time`; remove `DIGEST_AT`)
- Test: `tests/test_scheduler.py`, `tests/web/test_overview.py`

**Interfaces:**
- Produces: `parse_hhmm(s: str) -> datetime.time` in `config.py`.

- [ ] **Step 1: Write failing tests:**
  - `test_digest_job_uses_setting`: with `digest_time="19:30"`, the digest job trigger fields are hour 19 and minute 30.
  - Update `test_next_digest_is_0800_tunis` to pass `time(8, 0)`, and add a case with `time(19, 30)`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: digest time is a setting`.

### Task 5: Profile editor and re-score

**Files:**
- Create: `src/prospector/profile/form.py` (`profile_from_form(form: FormData) -> Profile`, which raises `ValidationError`; `profile_to_form(p: Profile) -> dict`; `save_profile(path: Path, p: Profile) -> None`, which writes `.bak` then saves atomically as YAML with `sort_keys=False, allow_unicode=True`)
- Modify: `src/prospector/pipeline.py` (`rescore_all(ctx: AppContext, now: datetime) -> int`)
- Modify: `src/prospector/web/settings.py` (`POST /settings/profile` and `POST /settings/rescore`; `GET /settings` renders `#profile`)
- Modify: `src/prospector/web/templates/settings.html`
- Create: `src/prospector/web/static/app.js`, starting with the add/remove-row helpers only; the template refers to it from `base.html`
- Test: `tests/profile/test_form.py`, `tests/test_rescore.py`, `tests/web/test_settings_page.py`

**Interfaces:**
- Form field names use bracketed indices:
  - `skills[i][name]`, `skills[i][weight]`.
  - `projects[i][name]`, `projects[i][writeup]`, `projects[i][tags]` (comma list).
  - `kinds` (multi), `regions` (comma list).
  - `exclude_unpaid` (checkbox).
  - `min_pay[i][currency|period|amount]`.
  - `languages`, `blocked_keywords`, `blocked_companies` (comma lists).
  - `boost[i][keyword]`, `boost[i][weight]`.
  - Rows with an empty name or keyword are dropped.
- `rescore_all`:
  - Recomputes `ctx.profile_vecs = profile_vectors(ctx.profile, ctx.embedder)`, or an empty `(0, dim)` array when there are no projects.
  - For each lead with a stored embedding, calls `score_stage1` exactly as `_score` does and calls `save_stage1`. Stage-2 is never touched.
  - Returns the count, and sets kv `rescore_status` to `{"state": "running"|"done", "count": n}`.
- `POST /settings/rescore` calls `ctx.run_background(lambda: rescore_all(ctx, now))` and returns a fragment "Re-scoring N leads…".

- [ ] **Step 1: Write failing tests:**
  - `test_round_trip_example`: `profile_to_form(load_profile("profile.example.yaml"))` → MultiDict → `profile_from_form` gives an equal `Profile`.
  - `test_bad_weight_rejected`: `skills[0][weight]=7` raises.
  - `test_empty_rows_dropped`.
  - `test_save_writes_bak`.
  - `test_rescore_changes_stage1_keeps_stage2`: use a fake embedder (deterministic vectors, as the pipeline tests do). Insert a lead plus embedding plus stage-1 0.1 plus a stage-2 dict, change the profile, run `rescore_all`. Stage-1 changes and stage-2 is equal.
  - `test_rescore_with_no_projects`: a profile with `projects=[]` returns a count and doesn't crash.
  - `test_profile_post_saves_and_restarts`.
  - `test_profile_post_invalid_400`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Check whether `profile_vectors` already handles empty projects. If not, guard in `rescore_all` and in `_score`.
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: profile editor and re-score existing leads`.

### Task 6: Test buttons

**Files:**
- Modify: `src/prospector/web/settings.py` (`POST /settings/test/llm`, `/settings/test/telegram`, `/settings/test/email`, `/settings/test/source/{source_id}`)
- Modify: `src/prospector/web/templates/settings.html` (`#tests` section; each button targets its own result `<span>`; the LLM result also fills `<datalist id="llm-models">`)
- Test: `tests/web/test_settings_tests.py`

**Interfaces:**
- Consumes: `ctx.llm.list_models()`, `send_telegram`, `send_email_via_bridge` and `render_email(build_digest(...))`, `pipeline.ingest`, `ctx.run_background`.
- Produces: each route returns a fragment `<span class="test-ok|test-err">…</span>`. The LLM test also writes kv `llm_last_error` (`None` on success, the error string on failure), which Task 7 reads.

- [ ] **Step 1: Write failing tests** (respx):
  - `test_llm_ok_lists_models`: the response shows "3 models" and "glm-5.3-flash: available", and kv `llm_last_error` is None.
  - `test_llm_401_reports_without_url`: the text contains "401", no "http", and no API key. kv `llm_last_error` contains "401".
  - `test_llm_missing_when_ctx_llm_none`.
  - `test_telegram_sends_and_hides_token`: respx records the message text "Prospector test message ✓". An error response mentions no token.
  - `test_telegram_not_configured`.
  - `test_email_posts_signed_digest`.
  - `test_run_source_queues`: `run_background` spy called, response "queued". An unknown id gives 404.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** In `rank/stage2.review`, also set kv `llm_last_error` to `str(e)` on `LLMError` and to `None` on success.
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): settings test buttons`.

### Task 7: Setup checklist

**Files:**
- Create: `src/prospector/web/checklist.py` (`setup_items(settings: Settings, kv: KV, profile_path: Path, example_path: Path) -> list[ChecklistItem]`, with `ChecklistItem(text: str, href: str)`)
- Modify: `src/prospector/web/dashboard.py`, `src/prospector/web/templates/overview.html` (card at the top while items exist)
- Test: `tests/web/test_checklist.py`

**Interfaces:**
- Items, with hrefs, in this order:
  - LLM key placeholder/empty (`REPLACE_ME` or `""`), or `llm_last_error` contains `HTTP 401`/`HTTP 403` → `/settings#f-llm_api_key`.
  - No `telegram_token` or `telegram_chat_id` → `/settings#f-telegram_token`.
  - No `bridge_url` → `/settings#f-bridge_url`.
  - Access domain or AUD contains `REPLACE_ME` or is empty → `/settings#f-access_team_domain`.
  - Profile bytes equal `profile.example.yaml` bytes → `/settings#profile`.
- `example_path` is the packaged copy: add `profile.example.yaml` to the image at `/app/profile.example.yaml`. The Dockerfile already copies the repo root, so confirm. The router resolves it relative to the repo root with `Path(__file__).parents[3] / "profile.example.yaml"`, and a missing file skips that item.

- [ ] **Step 1: Write failing tests:**
  - `test_all_open_on_fresh_install`: placeholders and the profile copied from the example give 5 items in order.
  - `test_item_clears`: one test per condition.
  - `test_overview_hides_card_when_done`.
  - `test_overview_links_to_field`: `href="/settings#f-llm_api_key"`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): setup checklist on overview`.

### Task 8: Actions on detail, toast and undo

**Files:**
- Modify: `src/prospector/store/feedback.py` (`record(...) -> int` via `RETURNING id`; `delete(feedback_id: int) -> None`)
- Modify: `src/prospector/web/dashboard.py`:
  - `act` sets header `HX-Trigger: {"toast": {"msg": "Starred", "undo": "/lead/{id}/undo?to=<prev status>&fb=<feedback id>"}}`.
  - New `POST /lead/{id}/undo?to=&fb=` sets the status to `to` (it must be a `Status`), deletes feedback `fb` only when it belongs to that lead, and returns the row.
- Modify: `src/prospector/web/templates/detail.html` (action group using the same buttons; target `#detail-actions`, swap via a `_detail_actions.html` fragment). The `act` route renders `_detail_actions.html` instead of `_row.html` when the request sends header `HX-Target: detail-actions`.
- Modify: `src/prospector/web/static/app.js` (toast container; listens for the `toast` event; the Undo button issues `htmx.ajax('POST', undo, {target: '#lead-<id>' or '#detail-actions', swap: 'outerHTML'})`; auto-hides after 6 s)
- Modify: `src/prospector/web/static/app.css` (toast styles)
- Test: `tests/web/test_dashboard.py`

- [ ] **Step 1: Write failing tests:**
  - `test_action_sends_toast_with_undo`: the parsed `HX-Trigger` JSON has `msg == "Dismissed"` and an undo URL with `to=new`.
  - `test_undo_restores_and_removes_feedback`: star → undo. Status is NEW and `ctx.feedback.count() == 0`.
  - `test_undo_twice`: a second identical undo returns 200 and the status stays NEW.
  - `test_undo_other_leads_feedback_untouched`: `fb` from another lead is not deleted.
  - `test_detail_has_actions`: the detail page contains `hx-post="/lead/{id}/star"`.
  - `test_detail_action_returns_detail_fragment`: with header `HX-Target: detail-actions`, the response contains `id="detail-actions"`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): actions on detail page, toast with undo`.

### Task 9: Search and keyboard

**Files:**
- Modify: `src/prospector/store/leads.py` (`list(..., q: str | None = None)` adds `(l.title LIKE ? OR l.company LIKE ?)`; escape `%` and `_` with `ESCAPE '\'`)
- Modify: `src/prospector/web/dashboard.py` (`/leads` takes `q` and includes it in `query`)
- Modify: `src/prospector/web/templates/base.html` (search form `action="/leads"` in the top bar, `name="q"`, `id="search"`; help overlay markup `#shortcuts` with `hidden`)
- Modify: `src/prospector/web/static/app.js`:
  - Keys: `j`/`k` focus the next/previous `.lead` (`tabindex=0`, scrolled into view); `s`/`a`/`d` click that row's `.act-star`/`.act-applied`/`.act-dismiss`; `u` clicks the visible toast's Undo; `o` opens `data-url` in a new tab; Enter follows `.lead-title`; `/` focuses `#search`; `?` toggles `#shortcuts`; Escape closes it.
  - Shortcuts are ignored when the event target is an input, textarea, select or contenteditable, or when a modifier key is held.
- Modify: `src/prospector/web/templates/_row.html` (`tabindex="0"`, `data-url="{{ l.canonical_url }}"`)
- Test: `tests/store/test_store.py`, `tests/web/test_dashboard.py`

- [ ] **Step 1: Write failing tests:**
  - `test_search_title_and_company`: "rust" matches the title "Rust dev" and the company "RustCorp", and nothing else.
  - `test_search_escapes_wildcards`: `q="%"` matches only a title containing "%".
  - `test_leads_page_search_keeps_query_in_pager`.
  - `test_shortcut_help_present`: `id="shortcuts"` appears in `/leads`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): search and keyboard shortcuts`.

### Task 10: Readable lead details

**Files:**
- Create: `src/prospector/web/format.py`:
  - `fmt_pay(p: Pay | None) -> str`.
  - `fmt_ago(ts: datetime | str | None, now: datetime) -> str`.
  - `paragraphs(body: str) -> list[tuple[Literal["p", "ul"], str | list[str]]]`.
  - All three are registered as Jinja filters in `dashboard.py`; `fmt_ago` uses `datetime.now(UTC)` there.
- Modify: `src/prospector/normalize/normalize.py` (`clean_text(text, keep_lines: bool = False)`; `normalize` passes `keep_lines=True` for the body only)
- Modify: `src/prospector/web/templates/_row.html` (posted date: `fmt_ago` of `posted_at`, else first seen), `detail.html` (pay via `fmt_pay`; body via `paragraphs`)
- Modify: `src/prospector/store/leads.py` (`LeadRow` gains `created_at: str`, read in `_row`)
- Test: `tests/web/test_format.py`, `tests/normalize/test_normalize.py`

**Interfaces / exact outputs:**
- `fmt_pay`:
  - `Pay(60000, 80000, "USD", "year")` → `"$60–80k / year"`.
  - `Pay(500, None, "EUR", "fixed")` → `"€500 fixed"`.
  - `Pay(2000, 2000, "TND", "month")` → `"TND 2,000 / month"`.
  - `Pay(None, 50, "GBP", "hour")` → `"up to £50 / hour"`.
  - `None` → `"not stated"`.
  - Symbols: USD `$`, EUR `€`, GBP `£`; other currencies are prefixed by code plus a space. Use the `k` suffix only when both ends are ≥ 1000 and divisible by 1000.
- `fmt_ago` (`now` fixed):
  - 30 s → `"just now"`.
  - 5 min → `"5m ago"`.
  - 3 h → `"3h ago"`.
  - 2 d → `"2d ago"`.
  - 40 d → `"%d %b %Y"` absolute.
  - `None` → `""`.
- `paragraphs`:
  - Blocks separated by blank lines.
  - A block whose lines all start with `-`, `*` or `•` becomes `("ul", [items without bullet])`.
  - Everything else becomes `("p", text)`.
- `clean_text(keep_lines=True)`:
  - `"a  b\n\n\n\nc\t d"` → `"a b\n\nc d"`.
  - HTML `<p>x</p><p>y</p>` → `"x\n\ny"`, which needs `_BLOCK_END` to emit `\n\n`.
  - Default behaviour is unchanged.

- [ ] **Step 1: Write failing table tests** for the exact outputs above, plus `test_detail_renders_list`: a body `"Intro\n\n- one\n- two"` renders `<li>one</li>`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Check that the existing normalize and dedupe tests still pass, since titles still collapse.
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): readable pay, relative times, formatted descriptions`.

### Task 11: Browser check and deploy

- [ ] **Step 1:** Serve locally against a fresh snapshot of the server DB, using the scratchpad preview script. Check every page (overview, leads, detail, sources, settings) in light and dark at 1280 and 375 px: no horizontal scroll (`scrollWidth == clientWidth`).
  - Exercise: save a tuning value (the restart spy is a no-op locally), the checklist links, ★ → toast → Undo, `j`/`k`/`s`/`d`/`?`, and the search box.
- [ ] **Step 2:** Run the full suite. Push `main`. On the server, run `git pull --ff-only && sudo docker compose up -d --build`.
  - Verify `/healthz`, plus `/settings` 200 over Tailscale.
  - Save one harmless value (`llm_daily_cap` unchanged → restart). Confirm the container comes back healthy and the value shows "set here".
