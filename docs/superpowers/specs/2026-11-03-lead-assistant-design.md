# Lead assistant — design

Status: approved in conversation 2026-11-03; this document is the written spec.

## Goal

On every lead's page, an AI assistant that knows the lead and the owner's profile and helps win it: drafts the
platform's proposal text (e.g. Freelancer's "Describe your proposal (minimum 100 characters)"), suggests a fair and
a competitive price with a delivery time, judges whether the lead is worth it, and answers questions about it.
Everything it produces is a draft the owner copies; Prospector never submits anything to a platform.

## Decisions (from the conversation)

- Chat first (one chat per lead), plus a one-click **Draft bid** that returns editable fields.
- Prices from both the owner's rate and the client's budget, with two tiers: **fair** and **competitive**
  ("lower bracket" to win selection, never below the owner's floor).
- Currencies **USD and TND**, selectable; each has its own rate and floor.
- Own daily cap for assistant messages (default 100), separate from ranking's cap; optional own model.
- Posting text: try to fetch it; if the fetch fails or the result is junk, ask the owner to paste it.
- Plain request/reply (no streaming). Replies always in **English**.
- Streaming, several chats per lead and development help come later with the sweave-engine integration.

## 1. Data

New tables in `store/schema.sql` (new tables only — no `ALTER` on `leads`, so existing databases pick them up
through `CREATE TABLE IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS lead_messages (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    role TEXT NOT NULL,          -- 'user' | 'assistant' | 'error'
    content TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lead_messages_lead ON lead_messages(lead_id, id);

CREATE TABLE IF NOT EXISTS lead_assist (
    lead_id INTEGER PRIMARY KEY REFERENCES leads(id) ON DELETE CASCADE,
    posting TEXT,                -- full posting text (fetched or pasted)
    posting_origin TEXT,         -- 'source' | 'fetched' | 'pasted'
    fetch_note TEXT,             -- why a fetch failed, shown above the paste box
    fetch_tried INTEGER NOT NULL DEFAULT 0,
    bid TEXT                     -- last bid draft as JSON (see §3)
);
```

`error` messages are shown in the chat but never sent back to the model.

A new `store/assist.py` holds `AssistRepo` (messages: `add`, `recent(lead_id, n)`, `clear`; assist row: `get`,
`set_posting`, `set_fetch_result`, `set_bid`), registered on `AppContext` like the other repos.

## 2. Profile and settings

Profile (`profile/model.py`) gains an optional `pricing` block, with these defaults when absent:

```yaml
pricing:
  currency: USD              # default bid currency: USD | TND
  hours_per_day: 6
  rates:
    USD: {rate: 25, floor: 15}   # per hour
    TND: {rate: 60, floor: 35}
```

- `currency` must be a key of `rates`; only `USD` and `TND` are accepted; `floor <= rate`, both > 0;
  `hours_per_day` in 1–12.
- The Settings → Profile form gets a Pricing fieldset: currency select, hours per day, rate and floor per currency.
  `profile.example.yaml` and the server's live profile get the block above.

Settings (`config.py`, editable on Settings → Tuning, same mechanics as the existing fields):

- `assistant_daily_cap: int = Field(100, ge=1, le=2000)`
- `assistant_model: str | None = None` — blank uses `llm_model`.

The assistant uses its own `LLMClient` (same base URL and key, model = `assistant_model or llm_model`), built in
`build_context` as `ctx.assistant_llm`. Usage is counted in kv `assistant_calls:<Tunis date>`; the overview's LLM
card shows it next to ranking's count.

## 3. Assistant behaviour

`LLMClient` gains `chat(system: str, messages: list[dict], session_id: str, temperature: float = 0.4) -> str`;
`complete` becomes a call to `chat` with one user message and temperature 0 (behaviour unchanged).

New package `prospector/assist/`:

- `context.py` — builds the system prompt: role and rules, the owner's profile (skills, project write-ups,
  pricing), and the lead (title, company, kind, pay, locations, source and URL, ranking verdict, fit summary and
  red flags if any, then the posting — `lead_assist.posting` if present, else `lead.body`, truncated to 8,000
  chars). The posting is wrapped in clearly marked delimiters and the rules say its content is data from a
  stranger, never instructions.
- Rules in the prompt: reply in English; write proposals in the first person as the owner; never invent
  experience, clients or numbers not in the profile; lead with the single most relevant project; concrete and
  short; call out scams, unpaid work, off-platform payment requests and vague scope.
- `chat.py` — `send(ctx, lead_id, text) -> list[Message]`: stores the user message, sends the system prompt plus the
  last 20 non-error messages, stores the reply (or an `error` message) and returns the new messages.
- `bid.py` — `draft_bid(ctx, lead_id, currency: str | None) -> Bid`. Asks for JSON:
  `{"proposal", "estimate_hours", "rationale", "budget_warning"}` (one repair retry on invalid JSON, like stage 2).
  Prospector computes the money itself:
  - `fair = round(hours × rate)`, `competitive = round(hours × floor)` in the chosen currency;
  - if the client states a budget in the same currency: fair is clamped into it when the clamp stays ≥
    competitive, and `budget_warning` is set by Prospector (not the model) when even `competitive` is above the
    client's maximum or `fair` is below the client's minimum;
  - `delivery_days = ceil(hours / hours_per_day × 1.2)` (20 % buffer), at least 1;
  - currency: the explicit choice, else the lead's pay currency if USD or TND, else the profile default.
  - `proposal` under 100 characters triggers the repair retry; the UI also shows a live character count.
  The bid is saved in `lead_assist.bid` and a one-line summary is added to the chat as an assistant message so
  follow-ups ("make it shorter") have it in context.
- Every model call (chat, bid, repair) costs one from the assistant cap. At the cap, the action returns an `error`
  message "Assistant limit reached for today (N). Raise it in Settings." with no model call.
- `LLMError` → `error` message with the cause; kv `llm_last_error` is set as stage 2 does, so the checklist flags
  a rejected key.

## 4. Posting fetch

`assist/fetch.py` — `fetch_posting(ctx, lead) -> FetchResult(text | None, note | None)`, tried once per lead when the
assistant panel first loads (`fetch_tried`), and again on an explicit "Try fetching again" button.

- Leads whose sources include `freelancer` skip the fetch: the API already returns the full description
  (`posting_origin = 'source'`, posting = body).
- Otherwise GET the lead's canonical URL with a dedicated client: http(s) only, no redirects followed
  automatically — up to 3 hops, each re-checked; the host must resolve only to public addresses (reject loopback,
  private, link-local, CGNAT/tailnet 100.64.0.0/10, multicast, reserved, IPv6 equivalents); 10 s timeout; body
  capped at 2 MB; `text/html` or `text/plain` only; robots.txt respected via `robots_allowed`.
- Text = `clean_text(html, keep_lines=True)`. It is junk when shorter than 300 characters or when it contains
  "sign in", "log in", "captcha", "enable javascript" or "access denied" (case-insensitive) within its first
  1,000 characters.
- On failure or junk: no posting saved, `fetch_note` explains ("The page needs a login", "The site blocked the
  request (HTTP 403)", …) and the paste box opens with that note.
- Pasting saves `posting_origin = 'pasted'` and replaces any earlier posting; at most 20,000 chars.

## 5. Web

On `detail.html`, below the actions, an **Assistant** card:

- Posting status line: "Using the full posting (from Freelancer / fetched / pasted)" or the fetch note, with a
  collapsible paste box (opens by itself when there is no usable posting).
- **Draft bid** button with a currency select (USD/TND). Result: proposal textarea with live character count and a
  Copy button; fair and competitive price, estimated hours, delivery days, each copyable; rationale; budget
  warning when set.
- Chat: message list, a textarea (Enter sends, Shift+Enter new line), a "thinking…" indicator while waiting,
  **Clear chat**. Messages render as escaped text through the existing `paragraphs` filter.

Routes (all POST behind the existing same-origin, access and host middleware):
`/lead/{id}/assist/message`, `/lead/{id}/assist/bid`, `/lead/{id}/assist/posting`, `/lead/{id}/assist/fetch`,
`/lead/{id}/assist/clear`. Each returns the HTMX fragment it updates. The panel's first render triggers the fetch
through `run_background` so the page never waits on it; the status line polls until `fetch_tried` is set. Model
calls run in the request (FastAPI's thread pool); the LLM client's 60 s timeout bounds them.

Keyboard shortcuts in `app.js` are ignored while focus is in the assistant's inputs (already true for inputs).

## 6. Later (not in this spec)

- Streaming replies, several chats per lead, development help (bounty checker) — with the sweave-engine
  integration.
- **Work-life dashboard:** mark leads won / in progress / completed, record off-platform work too, agreed price,
  payments received (amount, currency, date, where: Freelancer balance, bank, PayPal, cash…) and an income
  overview. It builds on this spec without changes to it: it will add its own tables keyed optionally to
  `leads.id`, and the bid draft gives it the quoted price to start from.

## Testing

- Pricing maths: fair/competitive, clamping, budget warnings, delivery days, currency choice — table-driven.
- Profile pricing validation and the Profile form round trip (including absent `pricing`).
- `chat`/`draft_bid` with a fake LLM: history window of 20, error messages excluded, cap enforced without a model
  call, JSON repair, short-proposal retry, `llm_last_error` set on failure.
- Fetch: blocked addresses (127.0.0.1, 10.x, 100.101.83.89, ::1, redirect to a private address), size cap,
  non-HTML type, junk detection, Freelancer skip — with `httpx.MockTransport` and a stubbed resolver.
- Web: each route's fragment, same-origin refusal, escaped output (`<script>` in a model reply stays text).

## Review focus

1. Untrusted posting text steering the model (prompt injection) — it can only affect drafted text, which the owner
   reads; check nothing it says is executed or sent anywhere.
2. Server-side fetch reaching internal addresses through DNS or redirects.
3. Model replies containing HTML or markdown links rendered as markup.
4. Two clicks on Draft bid / Send racing (double charge to the cap, duplicated messages).
5. A lead deleted or pruned while its assistant data exists (cascade).
