# Reach, competition, alerts and seven new sources — design

Status: approved in chat 2026-11-05.

## Why

The owner is a student in Tunisia, graduating 2027, aiming for internships and junior roles,
remote work, gigs and bounties. Checking the server on 2026-11-05 found, in the 100 best-scored
leads:

- 43 have senior-level titles (senior, principal, lead, architect) and 2 are junior or intern;
- 30 ask for 4+ years of experience;
- at least 11 are remote but locked to a region (US, Canada, Palo Alto, Kansas). They still get
  the full remote score, because `Lead.remote_region` is parsed but never used;
- 2 of 1,735 leads have any feedback, so the feedback part of the score has nothing to learn from.

What helps most: apply only where he can be hired, apply early, go where there is less
competition, and make the ranking learn from him quickly. This round does those four things and
adds the seven sources a scouting pass verified on 2026-11-04.

Out of scope, for later: tracking which sources lead to replies (needs more application data),
a skill-gap report, CVs tailored to each lead (needs CV text extraction), and company career
boards (Greenhouse, Lever, Ashby) found through a SearXNG instance the owner will run himself.

## 1. Seven new sources

There is one adapter per source in `src/prospector/sources/`. Each follows the existing
`Source` protocol (`id`, `interval_hours`, `fetch(http) -> list[RawLead]`) and is registered in
`adapters.py`. Each has a test that reads a saved sample response from the fixtures and runs
through respx.

| id | Endpoint | Notes |
|---|---|---|
| `weworkremotely` | `https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss`, `…/remote-full-stack-programming-jobs.rss`, `…/remote-devops-sysadmin-jobs.rss` | RSS 2.0. The `<region>` text becomes `location_text = "Remote (<region>)"`. Every 4 h. |
| `jobicy` | `https://jobicy.com/api/v2/remote-jobs?count=50&tag=<t>` for tags `golang`, `c++`, `rust` | `jobGeo` becomes `location_text = "Remote (<jobGeo>)"`. `interval_hours = 6`, which keeps it within Jobicy's limit of one poll per hour. The lead links to Jobicy's job URL, which their terms require. |
| `golangprojects` | `https://www.golangprojects.com/rss.xml` | RSS. Every 6 h. |
| `tunisietravail` | `https://www.tunisietravail.net/wp-json/wp/v2/posts?search=<q>&per_page=20&_fields=id,date,title,link,excerpt,content` for q in `développeur`, `developpeur`, `informatique`, `stage`, `pfe` | WordPress REST. Title and content are HTML-unescaped and tag-stripped. `location_text = "Tunisia"`. Every 6 h. |
| `codeur` | `https://www.codeur.com/projects/c/developpement.rss` (no query string) | RSS, French gigs, `kind_hint = GIG`. **Gate:** before writing this adapter, read Codeur's terms (CGU). If they forbid automated reading, drop the adapter and record that in the ledger. |
| `gsoc` | `https://summerofcode.withgoogle.com/api/program/`, then `/api/program/<slug>/organizations/` | Uses the newest program whose contributor application deadline has not passed. If none qualifies, returns `[]`, which is normal between rounds. There is one lead per organisation whose `tech_tags` include c, c++ or go: the title is `GSoC <year>: <org name>`, the URL is the org's GSoC page, and the deadline is the contributor deadline. `kind_hint = INTERNSHIP`, `location_text = "Remote"`. Every 24 h. These endpoints are undocumented, so missing keys make it return `[]` and log a warning rather than raise. |
| `outreachy` | `https://www.outreachy.org/apply/project-selection/` | One HTML page parsed once a day. There is one lead per project block (title, community, skills, the "Final Applications Due" date as the deadline). `kind_hint = INTERNSHIP`, `location_text = "Remote"`. If no blocks parse, it returns `[]` and source health shows 0 leads. |

**Internship kind.** `Kind.INTERNSHIP = "internship"` is added, and `normalize/kind.py` sets it
from `kind_hint`. Profile load gains a migration: a profile whose `targets.kinds` contains `pfe`
also gets `internship`, so these leads are not filtered as "kind not targeted".

**Turned on at deploy.** All seven are added to the `enabled_sources` default and to the server's
`settings.json`.

## 2. Reachability

**Profile fields.**

- `targets.levels: list[Literal["intern", "junior", "mid", "senior", "lead"]]`. It defaults to all
  five, which leaves the behaviour of any profile that never set it unchanged. The owner's is set
  to `["intern", "junior"]` at deploy.
- `targets.work_from: list[str]` (lower-case region words). It defaults to
  `["worldwide", "anywhere", "emea", "africa", "mena", "tunisia", "france"]`.

Both can be edited in Settings → Profile → What you want: levels as checkboxes, work_from as
comma text like regions. They are also in the YAML view.

**`rank/reach.py`** holds:

- `lead_level(lead) -> str | None`. The title decides first, using whole-word, case-insensitive
  patterns:
  - lead: staff, principal, lead, architect, head of, director, manager, vp
  - senior: senior, sr, confirmé, expérimenté
  - mid: mid, intermediate
  - junior: junior, jr, graduate, entry, new grad, débutant
  - intern: intern, internship, stage, stagiaire, pfe, alternance, apprenti

  With no title match, the years of experience in the body decide. The largest
  `N+ years / N years of experience / N ans d'expérience / minimum N ans` with N < 30 maps
  N ≥ 5 → senior, 3–4 → mid, 1–2 → junior. Otherwise the result is `None`. A lead of kind
  internship or pfe is `intern`.
- `region_status(lead, work_from) -> ("ok" | "maybe" | "locked", label | None)`:
  - Remote leads with no region, or whose region contains a `work_from` word, are ok.
  - A region that is exactly or mainly "Europe", "EU", "European Union" or "CET" is maybe, labelled
    "Europe".
  - A region naming something on the lock list, and nothing on `work_from`, is locked, labelled from
    the match (e.g. "US only"). The lock list is US, USA, United States, U.S., America(s), North
    America, Canada, LATAM, Latin America, UK, United Kingdom, India, Australia, APAC, the 50 US
    state names and two-letter codes in the form `City, ST`, and a short city list (San Francisco,
    New York, NYC, Seattle, Austin, Palo Alto, Boston, Chicago, Toronto, London).
  - An unknown region string is ok.
  - Non-remote leads keep today's location logic, and region_status is ok for them.
- `reach(lead, profile) -> (factor: float, tag: str | None)`:
  - level: skipped for gig and bounty kinds and when `lead_level` is None. The level is ok when it is
    in `targets.levels`. It is a stretch when its rank is exactly one above the highest chosen level
    (order intern < junior < mid < senior < lead). Otherwise it is out.
  - The worse of the level and region results wins: ok → 1.0 with no tag; stretch or maybe → 0.75,
    tagged "Stretch" or "Europe"; out or locked → 0.35, tagged "Too senior" or the region label.

**Scoring.** `score_stage1` multiplies the final score by the reach factor, and by the competition
factor (section 3). The breakdown gains `reach`, `competition` and `reach_tag`. The weighted
components and `Weights` don't change, so learning never treats reach as a weight.

The lead list and detail show the reach tag as a small badge. The lead detail's score breakdown
shows reach and competition as multipliers.

**Stage 2.** The prompt adds `CANDIDATE LEVEL: <levels>` and `CAN WORK FROM: <work_from>`. The
system prompt adds: rate weak when the role needs a level well above the candidate's, or a location
the candidate can't work from. The cache key adds a hash of those two lines, so a change to the
profile re-reviews.

## 3. Competition

A new table `lead_signals(lead_id INTEGER PRIMARY KEY, bid_count INTEGER, updated_at TEXT)` is
created with CREATE TABLE IF NOT EXISTS. `LeadSignalsRepo` provides `set_bids(lead_id, n)` and
`bids(lead_id) -> int | None`.

The Freelancer adapter puts `bid_stats.bid_count` on a new optional `RawLead.bid_count`. On insert
and on the merge path, ingest saves it when it isn't None. A merge of a lead that already exists
saves the new count and re-scores that lead.

`competition_factor(bids)`:

| bids | factor |
|---|---|
| None | 1.0 |
| ≤ 10 | 1.0 |
| ≤ 30 | 0.9 |
| ≤ 50 | 0.8 |
| > 50 | 0.65 |

The lead list and detail show "N bids" when a count is known. `score_stage1` receives the bid
count through a new keyword argument, `bids: int | None = None`.

## 4. Instant alerts

There are three new settings, in Settings → Schedule and Work under an "Alerts" card. They are
editable live, with no restart:

- `alerts_enabled: bool = True`
- `alert_threshold: float = 0.60`, in the range 0–1
- `alert_daily_max: int = 6`, in the range 0–50

`notify/alerts.py: send_alerts(ctx, now) -> int` runs at the end of each `tick`, after stage 2. It
picks new leads (status new) that meet all of these:

- stage1 score ≥ the threshold
- reach tag is None
- `posted_at` within 24 h, or `created_at` within 24 h when posted_at is unknown
- id not in kv `alerted` (kept for the 500 most recent)

They are sent best first, up to the remaining daily allowance, counted in kv
`alerts:<Tunis date>`. Each message is one Telegram send:

```
<title>
<company> · <pay or "pay not stated"> · <score as %>
<"N bids" when known>
<dashboard_url>/lead/<id>
```

If Telegram isn't configured, or alerts are disabled, it sends nothing. A Telegram error is logged
and the lead isn't marked alerted, so it is retried on the next tick within the 24 h window.

## 5. Dismiss with a reason

Dismiss on the lead list and the lead detail opens a small menu: Too senior · Can't apply from
here · Wrong stack · Not interested · Other. Submitting it posts the action with `reason`. A plain
dismiss with no reason stays valid and is treated as "not interested". Undo works as it does today.

A new table `dismiss_reasons(feedback_id INTEGER PRIMARY KEY, reason TEXT NOT NULL)` links to the
feedback row. Reason keys are `too_senior`, `no_region`, `wrong_stack`, `not_interested` and
`other`.

`FeedbackRepo.negative_ids()` leaves out leads whose latest dismiss reason is `too_senior` or
`no_region`, so similar topics aren't punished for a level or region problem. Reweighting skips
those rows too.

**Detection misses.** Settings → Sources gets a card listing the last 20 leads dismissed as too
senior or can't-apply whose reach tag was None. Each row shows the title and region, which is the
evidence for improving the patterns.

## 6. Deploy

1. Back up `profile.yaml`, `settings.json` and `prospector.db` as `*.pre-reach`.
2. Set `targets.levels: [intern, junior]` in the owner's profile. Add the seven ids to
   `enabled_sources`.
3. Deploy, then re-score all leads. Verify that the top 100 drop most senior and region-locked
   titles, and record the before and after counts.

## Error handling

- A source that fails follows the existing health, backoff and drift rules. There is nothing new.
- Missing keys in the GSoC or Outreachy data give `[]` and a warning, never an exception that
  pauses the source.
- The reach patterns never raise. Bad input gives `None` or ok.

## Testing

- Each adapter has a fixture-based test of its parsed fields, and an empty or odd response returns `[]`.
- `lead_level` has a table of titles and bodies covering each level and the French terms. A false
  friend like "Leading provider seeks Go dev" must not read as lead: patterns match whole words,
  and "lead" counts only as a role word, i.e. at the start of the title or directly before or after
  engineer/developer/dev.
- `region_status` has a table: "Remote (US only)" is locked, "Remote (EMEA)" ok, "Remote (Europe)"
  maybe, "Remote (Anywhere in the World)" ok, "Remote (Austin, TX)" locked, "Remote" ok.
- `reach` checks the levels order and stretch logic, gigs skipping the level check, and that the
  worse result wins.
- A stage-1 test checks a senior lead scores lower than the same lead as junior, and that the
  breakdown has reach and competition.
- Alerts tests cover the threshold, the reach filter, the 24 h window, the daily max, de-duplication,
  retry after an error, and disabled or missing Telegram.
- Dismiss-reason tests cover storing the reason, leaving too_senior out of negatives, undo, and the
  misses list.
- Competition tests cover the factor table, the count saved on merge, and the badge.
