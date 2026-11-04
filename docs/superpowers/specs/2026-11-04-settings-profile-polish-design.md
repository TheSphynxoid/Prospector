# Settings, Profile and polish pass — design

Status: approved in conversation 2026-11-04, awaiting written-spec review.

## Purpose

Settings is one 11,900 px page with 136 fields and one "Save and restart" button. The owner can't see at a glance
what is set and working, every save restarts the app, and the profile editor is awkward. The lead assistant also
lacks real data about the owner and sometimes talks as if it were the one bidding. This pass:

1. splits Settings into a hub and one page per area, with live apply where possible;
2. redesigns the Profile (About you, Interests, AI helper, YAML view, CVs) and fixes the assistant's role;
3. polishes the other pages.

Out of scope: first-run onboarding wizard and guided tour (proposed, deferred), CV text extraction (later).

## 1. Settings structure

### Pages

- `/settings` — hub: one card per area with a status line.
- `/settings/connections` — status cards for LLM, Telegram, Email bridge, GitHub, Cloudflare Access. Each card:
  status dot (connected / not set / failing, from the last test or last real use), its fields, a Test button.
  Telegram's "Find my chat ID" lives in its card. Adzuna keys live in a collapsed "Other sources" card.
- `/settings/sources` — one row per source: on/off toggle, last run, count, last error, "needs credentials",
  Run now. Replaces `/health`, which redirects here (old digest links keep working).
- `/settings/ai` — models, daily caps (reviews, assistant), review threshold.
- `/settings/profile` — the Profile editor (section 2).
- `/settings/pricing` — rate, competitive floor, hours per day (stored in the profile's `pricing` block), USD → TND
  override, today's rates line (with "override in use" when set).
- `/settings/schedule` — digest time, follow-up days, expiry days.

Each page is its own form and Save. A sticky save bar appears when the form has unsaved changes
(client-side dirty check); leaving with unsaved changes asks first.

### Live apply vs restart

- Restart needed ("cold"): `llm_api_key`, `llm_base_url`, `llm_model`, `llm_fallback_model`, `assistant_model`,
  `enabled_sources`, `digest_time`, `access_team_domain`, `access_aud`, `github_token`, `adzuna_app_id`,
  `adzuna_app_key`.
- Everything else applies live: overrides are saved, `ctx.settings` is rebuilt from them, and dependants are
  refreshed (`ctx.fx.tnd_override`). Toast "Saved".
- The Save button reads **Save and restart** as soon as a cold field on that page is changed; after a restart
  the page waits for `/healthz` and reloads (existing behaviour).
- Profile saves never restart: the profile reloads in place; if skills, projects, About or interests changed,
  `ctx.profile_vecs` is cleared and the existing re-score job starts in the background with its progress shown.

## 2. Profile

### About you (new `about` block in profile.yaml, all optional)

- `name`, `headline`, `bio`, `location`, `timezone`
- `languages`: list of `{language, level}` (level: native / fluent / professional / basic)
- `years_experience`, `highlights`: list of short true statements
- `education`: list of `{school, degree, year}`
- `availability`: `{hours_per_week, earliest_start (date), open_to: [full_time, part_time, gigs, internship]}`
- `links`: `{github, portfolio, linkedin, freelancer, other}`

### Skills

Chips with a three-step weight: core 1.0 / strong 0.7 / some 0.4. Existing weights map to the nearest step;
a value that fits none shows as "custom" and is kept. Add with Enter, remove with ✕.

### Projects

One collapsible card each: name, tags (chips), write-up (textarea with character count and the hint
"Used for scoring and by the bid assistant"). Add, remove, reorder (move up/down).

### What you want and filters

Kinds as toggle chips; regions as chips. Filters: "Exclude unpaid" switch; minimum pay table
(amount, currency, period, add/remove); languages, blocked keywords, blocked companies as chip inputs.

### Interests (replaces boost keywords)

- Model: list of `{phrase, weight (-1..1, not 0), where: title | anywhere}`. Old `boost_keywords` load as
  interests with `where: anywhere`; saving writes `interests` only.
- Matching: whole word / phrase, case-insensitive (regex `\b`-bounded), in the title only or title + body.
  Negative weights lower the score; stage-1 keyword component clamps the sum as today.
- Live preview per interest: "matches N of your current leads" + up to 3 example titles
  (`GET /settings/profile/interest-preview?phrase=&where=`, over new/starred leads).
- Suggestions: words and two-word phrases frequent in starred/applied leads' titles, not already skills or
  interests, stop-words removed; shown as chips to add.

### AI helper

Uses `assistant_llm` and the assistant daily cap; nothing is saved until the owner presses Save.

- Project write-up from notes (paste notes or a README) → draft write-up.
- Suggest skills and interests from projects and About.
- Bio and headline drafts (short and long).

Each result shows as a draft with Use (fills the field client-side) / Discard. Cap reached or LLM error shows an
inline message.

### Edit as YAML

Advanced toggle showing the full profile as YAML in a textarea; saving validates with the Profile model and
shows errors with line numbers; nothing is written on error.

### CVs

- Several files, PDF or DOCX, ≤ 5 MB each, checked by content (PDF magic `%PDF`, DOCX zip with
  `word/document.xml`), not just the extension.
- Stored under `DATA_DIR/cv/<uuid>.<ext>`; metadata in table `cvs(id, label, language, filename, stored_name,
  size, content_type, is_main, uploaded_at)`.
- Label, language, main flag; download (served through the dashboard with `Content-Disposition: attachment`),
  replace, delete. Exactly one main when any exist.
- No parsing yet; the table and storage are what later features (fill About from CV, pick a CV per lead) use.

## 3. Assistant role

- RULES rewritten: the assistant is the owner's private assistant, addresses the owner as "you", never applies
  or bids itself; text meant for the client is written in the owner's voice, marked as a draft, and uses only
  facts from the profile (About, skills, projects, education, availability, links).
- The system prompt includes the About block (inside the owner section, outside the posting fence).
- Drafts in chat render as a separate "Draft to send" block with a copy button: the model wraps client-facing
  text in `<<<DRAFT … DRAFT>>>` markers, which the renderer turns into the block (markers stripped from stranger
  text as with the posting fence).

## 4. General polish

- Same page header, tabs, filter bar, empty states and buttons on Overview, Leads, Lead detail, Work, Settings.
- Leads list: aligned row layout (score, title, company, pay, source), filters collapse to one row on phones,
  count "Showing 50 of 949".
- Lead detail: tidier two columns, assistant card easier to reach, posting text at a readable line length.
- Top nav: compact menu on phones instead of horizontal scroll; Work shows a badge with follow-ups due.
- Visible focus everywhere, labels on every control, dark mode checked on every page touched.

## Testing

- Settings: each page renders; live fields apply without `restart()`; cold fields trigger it; Save button label
  switches; `/health` redirects; dirty-bar markup present.
- Profile: old `boost_keywords` load as interests; interest matching (whole word, title-only, negative weight);
  preview and suggestions endpoints; YAML round-trip and error lines; AI helper with a fake LLM (cap, error,
  draft never saved); About fields round-trip.
- CVs: upload valid PDF/DOCX, reject renamed files and > 5 MB, one main, download headers, delete removes file.
- Assistant: system prompt contains About and the new role rules; draft markers render as the draft block and
  can't be forged from posting text.
- Browser check at desktop and 375 px for every page touched.

## Build order

1. Settings hub and pages with live apply (Sources page absorbs /health).
2. Profile data model: About, Interests (with scoring change), CV storage.
3. Profile editor UI: chips, projects, interests preview/suggestions, YAML view, CVs.
4. AI helper and assistant role/draft blocks.
5. General polish.
