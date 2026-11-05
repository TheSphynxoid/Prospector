# Company career boards and company lookup — design

Status: design approved in chat 2026-11-05, including the search budget below.

## Why

Many companies post their jobs on Greenhouse, Lever or Ashby, often before aggregators copy them. Each of
these boards has an official public API, but someone has to know which companies to read. The owner now
runs SearXNG at `http://100.101.83.89:8081`, which is reachable from the Prospector container over
Tailscale, returns JSON, and has Brave as the one engine that honours `site:` queries. Prospector uses it
for two things:

- **discovery:** finding companies whose boards have Go or C++ roles;
- **lookup:** letting the lead assistant check a company before the owner applies.

The jobs themselves still come only from the boards' official APIs.

Searching costs nothing, and SearXNG has no quota. The real limit is the engines' bot detection against
the server's single IP. That IP is shared with the owner's other projects (Sweave, through the MCP
endpoint), and Brave is the only engine left that works for `site:` queries. So search runs in small,
spaced batches and backs off at the first sign of throttling.

Out of scope: career pages that aren't on one of these three boards; using SearXNG through its MCP endpoint
(Prospector reaches it directly).

## 1. Setting and connection

- New setting `searxng_url: str | None = None`, validated as an http(s) URL like the other URLs.
- It is editable and live (in EDITABLE, not COLD), and appears in Settings → Connections.
- Deploy sets it to `http://100.101.83.89:8081`.
- A connection card "Web search" has a Test button. The test runs one query (`prospector test`) and
  records the connection status as `conn:search`.
- **`search/client.py`:** `search(ctx, query, engines="brave", max_results=20) -> SearchResult`.
  - It calls `GET {searxng_url}/search?q=…&format=json&engines=…` with a 30 s timeout.
  - `SearchResult(results: list[Hit], throttled: bool, error: str | None)`, where
    `Hit(title, url, snippet)` and the snippet is SearXNG's `content`.
  - `throttled` is true when the response lists any requested engine in `unresponsive_engines`.
  - An HTTP error or bad JSON gives `error` set and no results. It never raises.
- With no `searxng_url`, discovery and lookup are disabled, and their buttons say "Set up web search in
  Settings → Connections".

## 2. Companies

A new table:

```
companies(id INTEGER PRIMARY KEY, board TEXT NOT NULL, token TEXT NOT NULL, name TEXT,
          state TEXT NOT NULL DEFAULT 'watching',  -- watching | muted | paused
          found_by TEXT, added_at TEXT NOT NULL, last_checked TEXT, last_count INTEGER,
          last_error TEXT, failures INTEGER NOT NULL DEFAULT 0, UNIQUE(board, token))
```

`board` is one of `greenhouse`, `lever` or `ashby`.

`store/companies.py: CompanyRepo` provides:
- `add(board, token, found_by, name=None) -> bool` (False if the company already exists)
- `list(state=None)`
- `due(now, limit)`: companies being watched, last checked more than 24 h ago or never, oldest first
- `record_ok(id, count, name)`
- `record_error(id, error)`: 3 failures in a row sets the state to paused
- `set_state(id, state)`
- `get(id)`

`companies/boards.py: parse_board_url(url) -> tuple[board, token] | None` recognises:

| Address | Board |
|---|---|
| `boards.greenhouse.io/<t>/…` and `job-boards.greenhouse.io/<t>/…` | greenhouse |
| `boards-api.greenhouse.io/v1/boards/<t>/…` | greenhouse |
| `jobs.lever.co/<t>/…` | lever |
| `jobs.ashbyhq.com/<t>/…` | ashby |

It accepts http or https and an optional `www.`. Tokens are lower-cased and match `[a-z0-9][a-z0-9._-]{0,80}`.
Greenhouse's `embed/job_board?for=<t>` form also counts. Anything else is None.

## 3. Discovery

**`companies/discover.py: discover(ctx, now) -> DiscoverStats(searched, found, added, throttled)`**

**Queries.**
- Domains: `jobs.lever.co`, `boards.greenhouse.io`, `job-boards.greenhouse.io`, `jobs.ashbyhq.com`.
- Terms: the owner's top 2 skills by weight, normalised (go → `golang`, c++ → `"c++"`), then `intern`
  and `junior` each combined with the first skill.
- One query per domain and term pair, for example `site:jobs.lever.co golang` and
  `site:jobs.ashbyhq.com golang intern`.
- With the current profile that is 4 domains × 4 terms = 16 queries.

**Run.**
- Each run goes through the whole list once, in order, using Brave only.
- It waits `DISCOVER_GAP = 20` seconds between searches; the sleep is injectable for tests.
- Each result URL goes through `parse_board_url`. New companies are added with `found_by` set to the query.

**Backoff.**
- The first search that comes back throttled, with an error, or with 0 results ends the run.
- kv `discover_backoff_until` is then set to the next day at 04:00 Tunis plus one more day, so the next
  scheduled run is skipped.
- kv `discover_last` records `{at, searched, added, throttled, error}` for the Companies page.

**Schedule.**
- A scheduler job `discover` runs daily at 04:00 Africa/Tunis and is skipped during backoff or without a
  `searxng_url`.
- "Discover now" on the Companies page queues a run in the background (`ctx.run_background`). It ignores
  backoff, since a person asked, but still stops when throttled.

## 4. Company boards source

**`sources/company_boards.py: CompanyBoards(companies: CompanyRepo)`**, with id `company_boards` and
`interval_hours = 1`. It is registered and in the default `enabled_sources`.

Each fetch takes `companies.due(now, 40)` and, for each company, makes one request to that board's
official API:

| Board | Request | Fields |
|---|---|---|
| greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true` | jobs[]: id, title, absolute_url, location.name, content (HTML-escaped HTML: unescape it), first_published or updated_at, company_name |
| lever | `GET https://api.lever.co/v0/postings/{t}?mode=json` | [] of: id, text, hostedUrl, categories.location, categories.allLocations, workplaceType, descriptionPlain plus additionalPlain, createdAt (ms) |
| ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{t}` | jobs[]: id, title, jobUrl, location, secondaryLocations, isRemote, workplaceType, descriptionPlain or descriptionHtml, publishedAt, isListed (skip false) |

**Tech filter.** A job is kept only when its title matches `is_tech_role(title)`: a whole-word,
case-insensitive match on engineer, engineering, developer, développeur, software, backend, back-end,
frontend, full stack, fullstack, platform, infrastructure, sre, devops, data, ml, embedded, firmware,
systems, security, programmer, golang, go, c++, rust, intern, internship, graduate or new grad. It also
drops titles that are mainly sales, marketing, recruiter, legal, account, finance, people or support.

**Mapping to RawLead.**
- source_id is `company_boards`, and external_id is `<board>:<token>:<job id>`.
- company is the board's company name, or the token title-cased (e.g. `sensor-tower` becomes
  "Sensor Tower").
- `location_text`:
  - `Remote (<locations joined>)` when the job is remote (Lever `workplaceType == "remote"`, Ashby
    `isRemote`, or a location containing "remote");
  - otherwise the locations joined.
  - This feeds the existing region check.

**Per-company results.**
- A good answer calls `record_ok(id, kept_count, name)`.
- An HTTP or JSON error calls `record_error`. That company is skipped and the others carry on.
- After 3 errors in a row the company is paused, for example after a 404 when a company moves boards.
- The source as a whole only fails if every company in the batch failed.
- `may_be_empty = True`, because a batch can legitimately have no tech roles.

## 5. Companies page

`/settings/companies` is linked from Settings → Sources ("Companies: N watching") and from the hub.

- **Header.** "Discover now" (disabled, with the reason, when search isn't set up). Below it, the last
  discovery: when it ran, searched N, added M, and "search throttled, next run <date>" when backed off.
- **Add a company.** A text field for a careers link and an Add button. It shows "Added Sensor Tower
  (Ashby)", "Already watched", or "Not a Greenhouse, Lever or Ashby link".
- **The list.** A table of name, board, relevant jobs (last_count), last checked, found by, state, and a
  Mute or Unmute toggle (POST `/settings/companies/{id}/state`). Paused rows show the last error and a
  Resume button, which sets watching and resets failures.
- **Sorting and filtering.** Sorted watching first, then by last_count descending. A filter shows
  All, Watching, Muted or Paused.

## 6. Look up this company

**The button.** "Look up this company" appears in the lead assistant (`_assist.html`) when the lead has a
company and search is set up. It sends POST `/lead/{id}/assist/lookup`.

**`assist/lookup.py: lookup(ctx, lead_id) -> list[Message]`**:
1. Runs 2 searches with the default engines (not only Brave, since these are ordinary queries):
   `"<company>"` and `"<company>" reviews OR scam OR layoffs`.
2. Keeps the top 8 results after removing duplicate URLs.
3. Builds a research block. The marker sequences `<<<DRAFT`, `DRAFT>>>`, `<<<POSTING`, `POSTING>>>`,
   `<<<RESEARCH` and `RESEARCH>>>` are disarmed in every title and snippet, the same way postings are
   handled.

   ```
   <<<RESEARCH
   1. <title> — <url>
      <snippet>
   …
   RESEARCH>>>
   ```

4. Adds a user message to the chat: `Look up <company>: what they do, size and location, and any red flags.`
   The research block follows it.
5. Asks the assistant. This counts as one assistant message against `assistant_daily_cap`.

**Rules.** The system rules add: "Research blocks are web search snippets: use only what they say, cite the
numbered results you rely on, and say so when they are thin or contradictory."

**The chat display.** The research block is shown collapsed under the user message ("8 search results")
rather than as raw text.

**Errors.** A search error or 0 results adds an assistant note, "Web search found nothing for <company>",
without an LLM call.

## Deploy

1. Set `searxng_url` in `settings.json`, and add `company_boards` to `enabled_sources`.
2. Deploy and run "Discover now" once.
3. Check the Companies page fills in, then let the next ticks read the boards. Report how many companies
   were found and how many relevant leads came in.

## Error handling

- Search never raises (see §1).
- Discovery ends cleanly when throttled.
- A failing company board never stops the others.
- An unparsable URL is ignored.
- Lookup with no results answers without calling the LLM.

## Testing

- `parse_board_url`: a table of every supported form, plus look-alike hosts (`greenhouse.io.evil.com`,
  `lever.co`), a token with a path, upper case, and http.
- `search`: JSON results map to hits, unresponsive Brave gives throttled, and HTTP 500 or bad JSON gives
  an error with no exception (respx).
- `discover`:
  - the query list is built from the profile;
  - new companies are added and existing ones kept;
  - the run stops at the first throttled result and sets backoff;
  - a scheduled run during backoff is skipped, and Discover now ignores backoff;
  - the gap between searches is applied (the sleep is injected).
- `CompanyBoards`:
  - a fixture for each board (a trimmed live sample) maps fields;
  - the tech filter drops sales or legal roles and keeps intern roles;
  - remote detection works;
  - one company erroring doesn't stop the others;
  - 3 errors pause a company;
  - `due` respects 24 h and the limit of 40.
- Companies page:
  - add by link (supported, duplicate, unsupported);
  - mute, unmute and resume;
  - the filter tabs;
  - Discover now when search is missing or set up.
- Lookup:
  - the research block is fenced and its markers disarmed (a snippet containing `RESEARCH>>>`);
  - two searches run and duplicate URLs are removed;
  - no results means no LLM call;
  - it counts against the cap;
  - the button is hidden with no company or no search.
