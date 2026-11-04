# Work-life area and currency — design

Status: approved in conversation 2026-11-04, awaiting written-spec review.

## Purpose

Prospector finds leads. This adds what happens after: the applications you send, the work you win, the
money it brings in and where that money sits. The goal is one place that answers "what am I waiting on,
what am I working on, how much have I earned and where is it" — for any work, not only work found by
Prospector. UI/UX quality is a first-class requirement: it has to be pleasant to use daily, on a phone too.

Single user (the owner), same access model as the rest of the dashboard.

## Decisions made with the owner

- Tracks **any work**: entries may link to a lead, or be added by hand (direct clients, referrals, PFE stipend).
- **Separate Work area**, not more lead statuses. Leads keep meaning "is this posting good".
- Money: designed for **balances with transfers** (option B). Build order: payments and accounts first,
  transfers and balances second, same data model.
- Pipeline starts at the **application**, with follow-up reminders; reminders go through the daily digest
  (Telegram and email) and the dashboard. No separate on-the-day Telegram ping for now.
- **Currency done once**: daily automatic exchange rates, manual override possible, every payment keeps the
  rate of its day.
- Language: English. Amounts: USD first, TND equivalent under it.

## Currency

### Rates

- New module `prospector/fx.py`. Supported currencies: `USD, EUR, TND, GBP` (a list constant; adding one is one entry).
- Daily job `fx` (scheduler, 03:30 Africa/Tunis, and once at startup if today's rates are missing):
  1. `https://open.er-api.com/v6/latest/USD` (`result == "success"`, `rates[CODE]`)
  2. fallback `https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json` (`usd[code]`)
- Stored in `fx_rates(day TEXT, code TEXT, per_usd REAL, source TEXT, PRIMARY KEY(day, code))`.
- Sanity check before storing: positive, finite, and within ±20% of the last stored value for that code
  (first value accepted as is). A failing source is recorded in source health as `fx` so the Sources page
  shows it like any other source; the last known rate keeps being used.
- `rate(code, day=None) -> float`: USD is 1. Otherwise the manual override if set (TND only, see below),
  else the stored rate for `day` or the closest earlier day, else the closest later day, else a built-in
  constant (TND 3.0, EUR 0.92, GBP 0.79) with the warning above. Never raises.
- `to_usd(amount, code, day=None)` and `from_usd(usd, code, day=None)`.

### Settings

- `usd_tnd_rate` becomes `float | None = None`: blank means automatic. Help text: "Blank uses today's rate."
- Settings shows today's rates and their source and date under the field (read-only line).

### Use elsewhere

- Every place that shows a TND equivalent (lead assistant, bid card, Work area) uses `fx.rate("TND")`.
- The bid pricing converts a client budget in a supported currency to USD before clamping, instead of
  "Client budget is in EUR — compare yourself." Unsupported currencies keep that note.

## Data model (new tables in schema.sql)

Amounts are stored as **integer thousandths** of the currency unit (`amount_milli`) so TND millimes are exact.

- `accounts(id, name UNIQUE, currency, archived INT DEFAULT 0, created_at)`
- `applications(id, lead_id NULL REFERENCES leads, title, client, source, kind, url, applied_on, stage,
  follow_up_on NULL, follow_ups INT DEFAULT 0, next_step TEXT NULL, closed_on NULL, notes, created_at, updated_at)`
  - `stage`: `waiting | interview | won | rejected | no_reply | withdrawn`
  - unique index on `lead_id` where not null (one application per lead)
- `app_events(id, application_id, at, kind, text)` — timeline: applied, followed_up, stage_changed, note.
- `works(id, application_id NULL, lead_id NULL, title, client, kind, price_milli NULL, currency, stage,
  started_on, ended_on NULL, notes, created_at, updated_at)`
  - `stage`: `in_progress | delivered | closed | cancelled`
- `payments(id, work_id, amount_milli, currency, status, due_on NULL, received_on NULL, account_id NULL,
  usd_rate REAL NULL, usd_milli NULL, note, created_at)`
  - `status`: `expected | received`. On receive: `received_on`, `account_id` required; `usd_rate` and
    `usd_milli` are frozen from `fx.rate(currency, received_on)`.
- `transfers(id, on_day, from_account, to_account, sent_milli, received_milli, note, created_at)` (step 2)
  - effective rate = received/sent in the two accounts' currencies; fee shown as the difference from the
    market rate of that day, in USD.
- `kind` reuses the lead `Kind` values; `source` is free text prefilled from the lead's source.

Balances (step 2): per account = received payments into it + transfers in − transfers out, in the account's
currency; USD equivalent at today's rate.

## Flows

### Application from a lead
- Marking a lead *Applied* (existing action) creates its application if none exists: title, client, source,
  kind, url copied; `applied_on` today; `stage` waiting; `follow_up_on` today + `followup_days` (new setting,
  default 7, 1–60). The toast says "Marked applied · tracking in Work".
- Undo of that action deletes the application only if it has no events besides "applied" and was created by
  it. Otherwise it stays.
- The lead detail page shows an "Application: waiting · follow up Tue" line linking to it.

### Manual entry
- Work area "Add" offers: application, work, payment (to an existing work), account, transfer (step 2).

### Follow-ups
- An application is **due** when stage is `waiting` or `interview` and `follow_up_on <= today`.
- Actions on a due item: **Followed up** (event; `follow_ups += 1`; `follow_up_on` += followup_days),
  **Interview / next step** (stage interview, `next_step` text, `follow_up_on` = chosen date),
  **Won**, **Rejected**, **No reply**, **Snooze** (pick a date).
- Auto close: a `waiting` application with `follow_ups >= 1` whose `follow_up_on` is more than
  followup_days in the past becomes `no_reply` (event "closed: no answer"). Runs in the daily digest job,
  before the digest is built. (Meaning: after you followed up once and a full period passed again with no
  update, it closes.)
- **Won** creates a work item (title, client, kind, lead link; price from the lead's pay if fixed and
  single-valued, else empty) and opens its page.

### Work and payments
- Work stages move by buttons on the work page; `ended_on` set on closed/cancelled.
- Payments added inline on the work page: expected (amount, currency, due date) or received (amount,
  currency, date, account). An expected payment has "Mark received" (date defaults today, account defaults
  to the last used).
- Work row shows "paid X of Y" when a price is set.

## UI

New nav entry **Work** (`/work`), between Leads and Sources. Four tabs:

1. **Overview** (`/work`)
   - Tiles: received this month (USD, TND under), expected (with "N due this week"), active work
     (with delivered count), applications in the last 30 days (replies, won).
   - Follow-ups due (warning-tinted card) with the actions inline.
   - Applications pipeline: four compact columns Waiting / Interview / Won / Closed with counts and the
     first few titles.
   - Active work with a paid-so-far bar.
   - Accounts with balances (step 1: received totals per account; step 2: true balances) and
     "Record transfer" (step 2).
2. **Applications** (`/work/applications`): list with stage and source filters (same lenient filter
   handling as /leads); detail page with timeline, notes, actions.
3. **Work** (`/work/jobs`): list by stage; detail page with stage buttons, payments, links to
   application and lead.
4. **Money** (`/work/money`): payments and transfers by date, filter by account and month, monthly
   totals for the current year (simple bar row, no chart library).

Rules: HTMX in-place actions with the existing undo toast; forms ask only what is needed with sensible
defaults; every page works at phone width; empty states invite the first action ("Add your first
application"); reuse existing CSS tokens and components.

Main Overview gets one tile: "Work: $X this month · N follow-ups due", linking to /work.

## Digest

`build_digest` gains a "Follow up" section (due applications: title, how long ago, stage) in Telegram and
email, placed before new leads. Empty section omitted.

## Out of scope (later)

Invoices, taxes, recurring payments, multi-user, charts library, separate Telegram reminders, sweave
integration.

## Testing

- fx: parsing both sources, fallback order, sanity bound, override, nearest-day lookup, never-raise default.
- store: each repo's CRUD, milli conversion round-trip, frozen USD on receive, balances with transfers.
- flows: lead applied → application (idempotent), undo rule, due computation, auto no-reply, won → work.
- web: each page renders empty and populated, filters tolerate empty/bad values, actions return fragments
  with toasts, phone-width smoke check in the browser.
- digest: follow-up section in both formats, omitted when empty.

## Build order

1. Currency (fx module, job, settings, existing TND uses, bid conversion).
2. Applications + follow-ups + digest section + lead hook.
3. Work + payments + accounts + Overview tiles.
4. Money tab, transfers and balances.

Each step ships on its own.
