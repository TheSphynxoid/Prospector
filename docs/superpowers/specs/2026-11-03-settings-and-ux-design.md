# Prospector — Settings page and UX pass

Status: approved in conversation 2026-11-03. Builds on `2026-11-03-prospector-design.md`.

## 1. Goal

Let the owner configure Prospector from the dashboard (keys, tuning, profile, quick tests) instead of SSH, and
make the dashboard faster to work through (setup checklist, actions with undo everywhere, search, keyboard,
readable lead details).

Success: after this ships, the remaining README setup steps that only change Prospector's own configuration
(LLM key, Telegram, Worker URL, Access values, Adzuna/GitHub keys, profile) can all be done in the browser, and a
bad value can never lock the owner out of the dashboard.

## 2. Settings storage and precedence

- Overrides live in `DATA_DIR/settings.json`, file mode `0600`, written atomically (temp file + rename).
  `.env` stays on the host, outside the container, and is never written.
- Precedence, highest first: `settings.json` → process environment / `.env` → field defaults.
  Implemented as a pydantic-settings source (`settings_customise_sources`), so every existing `Settings` reader
  is unchanged.
- Each field's origin is reported as `override`, `env` or `default`. **Reset** deletes the key from
  `settings.json`, so the env value applies again.
- Editable fields (allow-list; anything else posted is ignored):
  - Keys & connections: `llm_api_key`*, `llm_base_url`, `telegram_token`*, `telegram_chat_id`, `bridge_url`,
    `bridge_secret`*, `access_team_domain`, `access_aud`, `adzuna_app_id`, `adzuna_app_key`*, `github_token`*,
    `dashboard_url`.
  - Tuning: `llm_model`, `llm_fallback_model`, `llm_daily_cap` (1–500), `stage2_threshold` (0–1),
    `enabled_sources` (known ids only), `digest_time` (new, `HH:MM`, Africa/Tunis, default `08:00`).
  - `*` = secret.
- Not editable: `data_dir`, `profile_path`, `embed_model` (changing it invalidates stored embeddings), and the
  compose-level `TAILSCALE_IP`.
- The scheduler and the overview's "next digest" read `digest_time` (replacing the hard-coded 08:00).

## 3. Saving and applying

- A save merges the form into the current overrides, then validates the merged result by constructing
  `Settings` with it, plus `check_secrets` (BRIDGE_SECRET of at least 32 chars). If validation fails, nothing
  is written and the form re-renders with the errors next to their fields.
- Saving restarts the app. A successful save writes the file, returns the "Restarting…" page, and then a
  background thread waits 1 s and calls `os._exit(0)`. Docker's `restart: unless-stopped` starts the app again.
  The page polls `/healthz` every 2 s and reloads `/settings` once the app answers; after 90 s it says the
  restart is taking longer than expected.
- Startup safety: if `settings.json` cannot be parsed, or the merged settings fail validation, the app logs the
  error, starts from env/.env only, and every page shows a red banner ("Your saved settings were ignored:
  <reason>"). The broken file is kept as `settings.json.rejected` and not deleted.

## 4. Security

- **Secrets are write-only.** A secret renders only as "set" / "not set". An empty input keeps the current
  value; a "Clear" checkbox removes the override. No secret value appears in any HTML response, log line or
  error message.
- **Revealing `BRIDGE_SECRET`.** The owner needs it to configure the Worker, so this secret alone can be shown.
  A Reveal button sends `POST /settings/reveal-bridge-secret`, which returns the value in a fragment with
  `Cache-Control: no-store`.
- **Same-origin check on every non-GET dashboard request** (settings, profile, tests, lead actions,
  needs-you). The request is refused with 403 when `Sec-Fetch-Site` is present and is not `same-origin`, or when
  `Origin` is present and its host does not match the request's `Host`. `/ingest/mail` is exempt: it is
  machine-to-machine and HMAC-signed. This also closes the deferred finding "Star/dismiss POSTs have no CSRF
  protection".
- Who can reach the page is unchanged: tailnet clients, or a valid Cloudflare Access JWT.
- The Access fields carry the note: "A wrong value only breaks the public address; Tailscale access keeps
  working."

## 5. Profile editor

- Structured form, not raw YAML:
  - Skills: rows of name + weight from 0 to 1, with add/remove.
  - Projects: name, write-up (textarea) and tags, with add/remove.
  - Target kinds: checkboxes. Regions: comma list.
  - Filters: exclude unpaid; min-pay rows (currency, period, amount); languages; blocked keywords; blocked
    companies.
  - Boost keywords: rows of keyword + weight.
- Saving validates the form through `Profile`. On success it copies the old file to `profile.yaml.bak`, writes
  the new file atomically, and restarts (same flow as §3).
- **Re-score existing leads** (button): runs in the background on the scheduler thread pool and recomputes
  stage-1 for every lead that has a stored embedding, using the current profile. While it runs the page shows
  "Re-scoring N leads…"; when it finishes, it shows the count in a toast. Stage-2 verdicts are kept.

## 6. Test buttons

These test the saved, running configuration. Each returns an inline success or error line, with errors passed
through `describe_error` so they never contain URLs or secrets.

- **Check LLM key:** `list_models()`. On success it shows the model count and whether the primary and fallback
  models are available, and the model inputs become `<datalist>` suggestions from that list.
- **Send test Telegram message:** "Prospector test message ✓".
- **Send test digest email:** sends the current digest through the bridge.
- **Run source now:** one button per enabled source. It queues a one-off scheduler job and answers "queued";
  the result appears on the Sources page.

## 7. UX

- **Setup checklist** on the overview, shown while any item is open:
  - LLM key missing, a placeholder, or rejected (last check-llm/stage-2 error was 401/403, recorded in kv).
  - Telegram not set.
  - Worker URL not set.
  - Access values are placeholders or empty.
  - Profile still byte-identical to `profile.example.yaml`.

  Each item links to the field or section that fixes it.
- **Actions everywhere:** ★ / Applied / ✕ / ↺ on the lead detail page. Every action answers with an
  `HX-Trigger` toast ("Dismissed · Undo"). Undo sends `POST /lead/{id}/undo`, which restores the previous status
  (passed in the toast) and deletes the feedback row the action created, so undo does not train the ranker. The
  toast auto-hides after 6 s.
- **Search:** a `q` box in the top bar, available on every page, does a case-insensitive `LIKE` match on title
  and company in `/leads`, combined with the other filters.
- **Keyboard** (`static/app.js`, vanilla, ignored while typing in an input):
  - `j` / `k` move focus between leads.
  - `s` star, `a` applied, `d` dismiss, `u` undo the last action.
  - `o` open the posting; Enter opens the detail page.
  - `/` focuses search; `?` toggles a shortcut help overlay.
- **Readable details:**
  - Pay formatter, e.g. "$60–80k / year", "€500 fixed", "TND 2,000 / month".
  - Relative-time filter ("3h ago", "2d ago"), with the absolute time in `title`.
  - Posted (or first-seen) date on each lead row.
  - Description formatting: `clean_text` keeps line breaks for bodies (spaces within lines collapse; 3+
    newlines become 2), and the detail page renders paragraphs and `-`/`•` lists. This applies to leads
    collected after the change; existing bodies stay flat. Titles and companies still collapse to one line.
    The content hash changes for new leads, which only affects the LLM cache.

## 8. Testing

- Settings: override beats env; Reset falls back to env; unknown fields are ignored; a failed validation writes
  nothing; a corrupt file falls back with a banner and is kept as `.rejected`; the written file is mode `0600`
  on POSIX.
- Secrets: render settings with every secret set and assert no secret value appears in the HTML. Reveal returns
  only `BRIDGE_SECRET` with `no-store`.
- Same-origin check: a POST with a foreign `Origin` or `Sec-Fetch-Site: cross-site` gets 403, a same-origin POST
  succeeds, and `/ingest/mail` is unaffected.
- Profile: a form round-trip reproduces `profile.example.yaml` semantically; an invalid weight is rejected;
  `.bak` is written; re-score changes stage-1 for existing leads and keeps stage-2.
- Tests endpoints: mocked HTTP; error text contains no URL or token.
- Checklist: each item appears and disappears under its condition.
- Undo restores the status and removes the feedback row. Search matches title and company. Pay and relative-time
  formatters are table-tested.
- `digest_time` drives both the scheduler trigger and `next_digest`.
- Browser: every page in light and dark mode at 1280 and 375 px, with no horizontal scroll; keyboard shortcuts
  and toast/undo exercised by hand.

## 9. Out of scope

Multi-user accounts, an audit log of setting changes, editing `TAILSCALE_IP` or compose settings, changing
the embedding model, re-flowing descriptions already stored flat.
