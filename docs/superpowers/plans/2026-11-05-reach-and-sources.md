# Reach, competition, alerts and seven new sources — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score leads by whether the owner can actually get them (level, region, competition), alert him early on the reachable ones, learn from dismiss reasons, and add seven verified sources.

**Architecture:** A new `rank/reach.py` gives a factor and a tag per lead; `score_stage1` multiplies the final score by the reach and competition factors. Bid counts live in a new `lead_signals` table, and dismiss reasons in `dismiss_reasons`. Alerts run at the end of each scheduler tick. Each source is a small adapter in `src/prospector/sources/` with a saved sample response for its test.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, HTMX, SQLite, pydantic 2, httpx and respx, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-reach-and-sources-design.md`

## Global Constraints

- Test command: `.venv/Scripts/python -m pytest -m "not slow" -q`. It must be green at the end of every task.
- No schema migrations: new tables use `CREATE TABLE IF NOT EXISTS` in `src/prospector/store/schema.sql`, and existing tables are not altered.
- Use only official APIs, feeds, or pages whose robots.txt allows reading, and fetch them with the shared `ctx.http` client, which carries the project's User-Agent.
- Level order: `intern < junior < mid < senior < lead`.
- Reach factors:

  | Result | Factor | Tag |
  |---|---|---|
  | ok | 1.0 | None |
  | stretch | 0.75 | `"Stretch"` |
  | maybe | 0.75 | `"Europe"` |
  | out | 0.35 | `"Too senior"` |
  | locked | 0.35 | region label |

- Competition factors: None or ≤10 → 1.0; ≤30 → 0.9; ≤50 → 0.8; >50 → 0.65.
- Alert defaults: `alerts_enabled=True`, `alert_threshold=0.60` (0–1), `alert_daily_max=6` (0–50). The 24 h window counts in the Africa/Tunis day, and the `alerted` kv list keeps at most 500 ids.
- Dismiss reason keys: `too_senior`, `no_region`, `wrong_stack`, `not_interested`, `other`.
- `targets.work_from` default: `["worldwide", "anywhere", "emea", "africa", "mena", "tunisia", "france"]`.
- `targets.levels` default: all five levels.
- Bash heredocs mangle `\n` and backslashes. Write regexes and templates with the Write or Edit tools.

## Review Focus

1. **Titles where "lead" or "manager" isn't the level.** "Product Manager intern", "Leading fintech hiring junior Go dev" and "Lead generation specialist" must read as intern, junior and None respectively. Test `test_level_false_friends` in Task 2.
2. **Region strings that mix allowed and locked places.** "USA, EMEA" and "Europe, Africa" are ok, because the owner is eligible in one of them. Test `test_region_mixed_ok` in Task 2.
3. **Stale or out-of-range breakdowns.** Leads scored before this change have no `reach` key, and the detail page and re-weighting must still render and work. Test `test_detail_renders_old_breakdown` in Task 4.
4. **Alerts after a restart.** The dedup list lives in kv, so a restart must not re-alert, and a lead that is rescored must not be alerted twice. Test `test_alert_not_repeated_after_rescore` in Task 7.
5. **Undoing a dismiss with a reason.** Undo removes the feedback row and its reason, and the lead goes back to the negatives as it was before. Test `test_undo_dismiss_reason` in Task 6.

---

### Task 1: Profile levels, work_from and the internship kind

**Files:**
- Modify: `src/prospector/models.py` (Kind), `src/prospector/profile/model.py` (Targets, migration), `src/prospector/profile/form.py`, `src/prospector/web/templates/settings/profile.html`
- Test: `tests/profile/test_reach_fields.py`

**Interfaces:**
- Produces:
  - `Kind.INTERNSHIP = "internship"`
  - `LEVELS: tuple[str, ...] = ("intern", "junior", "mid", "senior", "lead")` in `profile/model.py`
  - `Targets.levels: list[Literal[...LEVELS]]`, default all five
  - `Targets.work_from: list[str]`, default as in Global Constraints, lower-cased and stripped on validation
  - Form keys `levels` (checkbox list) and `work_from` (comma text)

- [ ] **Step 1: Write the failing tests**

```python
def test_targets_defaults():
    t = Targets(kinds=[Kind.JOB], regions=[])
    assert t.levels == ["intern", "junior", "mid", "senior", "lead"]
    assert t.work_from == ["worldwide", "anywhere", "emea", "africa", "mena", "tunisia", "france"]

def test_pfe_profile_gains_internship():
    p = Profile.model_validate({"skills": {}, "projects": [], "targets": {"kinds": ["job", "pfe"], "regions": []}})
    assert Kind.INTERNSHIP in p.targets.kinds

def test_profile_form_round_trip_levels(example_profile, ctx):
    # uses tests.web.test_settings_page helpers like test_regions_comma_text_saves
    pairs = [p for p in profile_form_of(client) if p[0] not in ("levels", "work_from")]
    pairs += [("levels", "intern"), ("levels", "junior"), ("work_from", "EMEA, Tunisia")]
    client.post("/settings/profile", data=as_form(pairs))
    assert ctx.profile.targets.levels == ["intern", "junior"] and ctx.profile.targets.work_from == ["emea", "tunisia"]
```

Also add `Kind.INTERNSHIP` to `test_models.py` if it enumerates the kinds.

- [ ] **Step 2: Run them.** Run `.venv/Scripts/python -m pytest tests/profile/test_reach_fields.py -q`. Expected: FAIL, because `levels` is not an attribute.
- [ ] **Step 3: Implement.**
  - Add `Kind.INTERNSHIP`.
  - Add the two `Targets` fields.
  - Extend the existing `model_validator(mode="before")` migration so that `pfe` in kinds also adds `internship`.
  - In the profile form, under "What you want": `levels` as checkboxes in LEVELS order, and `work_from` as a `data-chips` comma input like `regions`.
  - An empty `levels` submission is a field error, "Pick at least one level", shown on the profile page.
- [ ] **Step 4: Run them, then the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(profile): job levels, can-work-from regions, internship kind`.

---

### Task 2: Reach detection

**Files:**
- Create: `src/prospector/rank/reach.py`
- Test: `tests/rank/test_reach.py`

**Interfaces:**
- Consumes: `LEVELS`, `Targets.levels` and `Targets.work_from` (Task 1).
- Produces:
  - `lead_level(lead: Lead) -> str | None`
  - `region_status(lead: Lead, work_from: list[str]) -> tuple[str, str | None]`, where the status is "ok", "maybe" or "locked"
  - `reach(lead: Lead, profile: Profile) -> tuple[float, str | None]`

**Level patterns.** All patterns are whole-word and case-insensitive, checked against the title in this order: intern, junior, lead, senior, mid. The junior and intern words win because "Senior… internship" is rare, while "Product Manager intern" is common.
- intern: intern, internship, stage, stagiaire, pfe, alternance, alternant, apprenti, apprentice
- junior: junior, jr, graduate, entry level, entry-level, new grad, débutant
- lead, which matches only as a role word:
  - staff, principal, architect, head of, director, vp, cto
  - `manager` when it isn't followed by intern
  - `lead` or `tech lead` when it is the first word, or directly before or after engineer, developer, dev, programmer, software or ingénieur
- senior: senior, sr, confirmé, expérimenté
- mid: mid, mid-level, intermediate

If the title matches nothing, read years from the body: the largest N < 30 in `(\d{1,2})\s*\+?\s*(years?|yrs|ans)` that is followed within 30 characters by experience, expérience, or professional, or preceded by minimum, at least or au moins. N ≥ 5 → senior, 3–4 → mid, 1–2 → junior. A lead of kind internship or pfe returns "intern" before any pattern is checked.

**Region.**
- `region_status` checks `lead.remote_region`. A lead that isn't remote, or has no region, is "ok".
- Split the region on `,`, `/`, `|`, ` or ` and ` and `.
- If any part contains a work_from word, or worldwide, anywhere or global, the region is ok.
- Otherwise, if any part is Europe, EU, European Union, CET or CEST, it is "maybe" with label `"Europe"`.
- Otherwise, if any part matches the lock list from the spec, it is "locked". The label is `"<Name> only"`, with the name taken from the first match: "US", "Canada", "UK", "India", "Australia", "LATAM", "North America" or "APAC", and US states and cities give "US".
- Anything else is ok.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("title,body,level", [
    ("Senior Go Engineer", "", "senior"), ("Sr. Backend Dev", "", "senior"),
    ("Staff Software Engineer", "", "lead"), ("Lead Go Developer", "", "lead"),
    ("Junior C++ Developer", "", "junior"), ("Stage PFE Développeur Go", "", "intern"),
    ("Software Engineer", "You have 5+ years of professional experience", "senior"),
    ("Développeur Go", "minimum 3 ans d'expérience", "mid"),
    ("Software Engineer", "Our team of 40 engineers", None),
])
def test_lead_level(make_lead, title, body, level):
    assert lead_level(make_lead(title=title, body=body)) == level

def test_level_false_friends(make_lead):
    assert lead_level(make_lead(title="Product Manager intern")) == "intern"
    assert lead_level(make_lead(title="Leading fintech hiring junior Go dev")) == "junior"
    assert lead_level(make_lead(title="Lead generation specialist")) is None

@pytest.mark.parametrize("region,status,label", [
    ("US only", "locked", "US only"), ("EMEA", "ok", None), ("Europe", "maybe", "Europe"),
    ("Anywhere in the World", "ok", None), ("Austin, TX", "locked", "US only"),
    (None, "ok", None), ("Canada", "locked", "Canada only"), ("Mars colony", "ok", None),
])
def test_region_status(make_lead, region, status, label):
    assert region_status(make_lead(remote_region=region), DEFAULT_WORK_FROM) == (status, label)

def test_region_mixed_ok(make_lead):
    assert region_status(make_lead(remote_region="USA, EMEA"), DEFAULT_WORK_FROM)[0] == "ok"
    assert region_status(make_lead(remote_region="Europe, Africa"), DEFAULT_WORK_FROM)[0] == "ok"

def test_reach_combines(make_lead, prof):  # prof: levels intern+junior
    assert reach(make_lead(title="Junior Go dev"), prof) == (1.0, None)
    assert reach(make_lead(title="Go dev", body="3 years of experience"), prof) == (0.75, "Stretch")
    assert reach(make_lead(title="Senior Go dev"), prof) == (0.35, "Too senior")
    assert reach(make_lead(title="Junior Go dev", remote_region="US only"), prof) == (0.35, "US only")
    assert reach(make_lead(title="Senior bounty", kind=Kind.GIG), prof) == (1.0, None)
    assert reach(make_lead(title="Senior Go dev", remote_region="US only"), prof)[0] == 0.35
```

- [ ] **Step 2: Run them.** Run `.venv/Scripts/python -m pytest tests/rank/test_reach.py -q`. Expected: FAIL with ImportError.
- [ ] **Step 3: Implement** `rank/reach.py`. The worse of the level and region results wins. When both give the same factor, the level tag is used.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(rank): reach — lead level and region-lock detection`.

---

### Task 3: Bid counts

**Files:**
- Modify: `src/prospector/models.py` (RawLead), `src/prospector/store/schema.sql`, `src/prospector/sources/freelancer.py`, `src/prospector/pipeline.py` (ingest), `src/prospector/context.py`
- Create: `src/prospector/store/signals.py`
- Test: `tests/store/test_signals.py`, plus an addition to `tests/test_pipeline.py`

**Interfaces:**
- Produces:
  - `RawLead.bid_count: int | None = None`
  - `LeadSignalsRepo(conn)` with `.set_bids(lead_id: int, n: int) -> None` (an upsert that sets updated_at) and `.bids(lead_id: int) -> int | None`
  - `ctx.signals: LeadSignalsRepo`
  - `competition_factor(bids: int | None) -> float`, in `rank/reach.py`

- [ ] **Step 1: Write the failing tests**
  - `test_competition_factor`: the factor table at 0, 10, 11, 30, 31, 50, 51 and None.
  - `test_freelancer_bid_count`: the existing fixture carries `bid_stats.bid_count`. If the fixture lacks it, add `"bid_stats": {"bid_count": 52}` to the first project. The test asserts that the RawLead gets 52.
  - `test_ingest_saves_and_refreshes_bids`: ingest a fake source twice for the same URL, with bid_count 5 then 40. `ctx.signals.bids(id) == 40`, and the lead was re-scored (its `scored_at` changed).
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Add the table `lead_signals(lead_id INTEGER PRIMARY KEY, bid_count INTEGER, updated_at TEXT NOT NULL)`.
  - On insert, ingest saves bids before `_score`. On the merge path, when `raw.bid_count is not None`, it saves the count and calls `_score(ctx, existing, now)`, but only when existing.status is new.
- [ ] **Step 4: Run the suite.** Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(rank): track Freelancer bid counts`.

---

### Task 4: Reach and competition in the score and the UI

**Files:**
- Modify: `src/prospector/rank/stage1.py`, `src/prospector/pipeline.py` (`_save_stage1`, `rescore_all`), `src/prospector/web/dashboard.py`, `src/prospector/web/templates/_row.html`, `src/prospector/web/templates/detail.html`, `src/prospector/web/static/app.css`
- Test: `tests/rank/test_stage1.py`, `tests/web/test_reach_ui.py`

**Interfaces:**
- Consumes: `reach`, `competition_factor` and `ctx.signals.bids`.
- Produces:
  - `score_stage1(..., now, sim_range=..., bids: int | None = None)`. The final score is the weighted sum times the reach factor times the competition factor, clamped.
  - The breakdown gains the float keys `reach` and `competition`.
  - Template globals `reach_tag(lead) -> str | None` and `bids_of(lead_id) -> int | None`.

**Ruling vs spec.** The spec puts `reach_tag` in the breakdown. Keep the breakdown all floats, which is what the detail table and re-weighting expect. Instead, compute the tag at render time from the live profile with `reach(lead, ctx.profile)[1]`. That way a level change shows at once without waiting for a re-score.

- [ ] **Step 1: Write the failing tests**
  - Update `test_breakdown_has_all_components` so the set includes `reach` and `competition`.
  - `test_senior_scores_lower`: the same lead with the title "Senior Go dev" against "Junior Go dev" scores 0.35 as much, using `pytest.approx` with a fixture profile whose levels are intern and junior.
  - `test_bids_lower_score`: `bids=60` gives 0.65 of the score with `bids=None`.
  - `test_row_shows_reach_tag_and_bids` (web): a senior lead's row contains `Too senior`, and with `ctx.signals.set_bids(id, 52)` it contains `52 bids`.
  - `test_detail_renders_old_breakdown`: a score saved with the old 7-key breakdown renders with status 200.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `_save_stage1` passes `bids=ctx.signals.bids(lead.id)`.
  - `rescore_all` does the same.
  - The row shows a `chip chip-reach` with the tag, and a `chip` with "N bids".
  - The detail breakdown shows `reach` and `competition` as `×0.35`, and the other keys stay `%.2f`.
  - The CSS uses the existing `--warn` and `--bad` tokens: the "Too senior" or locked chip uses `--bad`, and "Stretch" or "Europe" uses `--warn`.
- [ ] **Step 4: Run the suite.** Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(rank): reach and competition multiply the score; tags on leads`.

---

### Task 5: Stage 2 knows the level and region

**Files:**
- Modify: `src/prospector/rank/stage2.py`
- Test: `tests/rank/test_stage2.py` (add tests)

**Interfaces:**
- Produces: `_user_prompt` includes the lines `CANDIDATE LEVEL: intern, junior` and `CAN WORK FROM: emea, tunisia, …`. `_cache_key(lead, profile)` is `f"llm:{lead.content_hash}:{h}"`, where `h` is the first 8 hex characters of sha256 of those two lines. Callers pass `profile`.

- [ ] **Step 1: Write the failing tests**
  - `test_prompt_has_level_and_region`
  - `test_cache_key_changes_with_levels`: the key differs when levels change.
  - The SYSTEM text contains "well above the candidate's level".
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Append this sentence to SYSTEM: `Rate weak when the role needs a level well above the candidate's level, or a location the candidate cannot work from.`
- [ ] **Step 4: Run the suite.** Expected: PASS. Old `llm:<hash>` cache entries are simply no longer read, which costs one re-review per top lead within the daily cap.
- [ ] **Step 5: Commit** with message `feat(rank): stage 2 weighs level and work-from`.

---

### Task 6: Dismiss with a reason

**Files:**
- Modify: `src/prospector/store/schema.sql`, `src/prospector/store/feedback.py`, `src/prospector/web/dashboard.py` (`act`, `undo`), `src/prospector/web/templates/_row.html`, `src/prospector/web/templates/_detail_actions.html`, `src/prospector/web/static/app.js`, `src/prospector/web/static/app.css`, `src/prospector/web/settings/__init__.py` and `templates/settings/sources.html` (misses card)
- Test: `tests/web/test_dismiss_reasons.py`, `tests/store/test_feedback.py`

**Interfaces:**
- Produces:
  - `REASONS: dict[str, str]`, ordered: `too_senior` "Too senior", `no_region` "Can't apply from here", `wrong_stack` "Wrong stack", `not_interested` "Not interested", `other` "Other".
  - `FeedbackRepo.record(lead_id, action, reason: str | None = None) -> int`. It stores the reason when the action is dismiss and the reason is in REASONS. An unknown reason becomes `not_interested`.
  - `FeedbackRepo.delete` also deletes the reason row.
  - `FeedbackRepo.negative_ids()` leaves out leads whose latest feedback is a dismiss with reason too_senior or no_region.
  - `FeedbackRepo.misses(limit=20) -> list[int]` returns the lead ids of the latest too_senior or no_region dismissals, newest first.
  - `POST /lead/{id}/dismiss` accepts an optional form field `reason`.

- [ ] **Step 1: Write the failing tests**
  - `test_dismiss_reason_stored`: posting `reason=too_senior` stores it, and the lead id is not in `negative_ids()`.
  - `test_wrong_stack_is_negative`: `reason=wrong_stack` puts the lead in `negative_ids()`.
  - `test_plain_dismiss_still_works`: a dismiss with no reason is in the negatives.
  - `test_undo_dismiss_reason`: undo removes both rows.
  - `test_misses_card`: a too_senior dismiss of a lead whose `reach_tag` is None appears on `/settings/sources` under "Detection misses", and one whose tag is "Too senior" doesn't.
  - `test_dismiss_menu_rendered`: the row html contains `data-dismiss-menu` and the five labels.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The table is `dismiss_reasons(feedback_id INTEGER PRIMARY KEY, reason TEXT NOT NULL)`.
  - The ✕ button becomes a `<details class="dismiss-menu" data-dismiss-menu>` with a `<summary>` ✕ and five buttons. Each button `hx-post`s `/lead/{id}/dismiss` with `hx-vals='{"reason": "<key>"}'` and the same target and swap as today.
  - Escape and a click outside close the menu, in app.js.
  - The Sources page card lists up to 20 misses, each with the title linked to the lead, the remote_region and the reason label. With none, it shows "No misses yet."
- [ ] **Step 4: Run the suite.** Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(feedback): dismiss reasons; level and region misses don't train topics`.

---

### Task 7: Instant alerts

**Files:**
- Modify: `src/prospector/config.py` (three fields, EDITABLE), `src/prospector/web/settings/pages.py` (schedule area fields and description), `src/prospector/pipeline.py` (tick)
- Create: `src/prospector/notify/alerts.py`
- Test: `tests/notify/test_alerts.py`

**Interfaces:**
- Consumes: `reach`, `ctx.signals.bids`, `send_telegram(http, token, chat_id, text)` and `fx.today(now)`.
- Produces:
  - `Settings.alerts_enabled: bool = True`
  - `Settings.alert_threshold: float = Field(0.60, ge=0, le=1)`
  - `Settings.alert_daily_max: int = Field(6, ge=0, le=50)`
  - All three are in EDITABLE and not in COLD.
  - `send_alerts(ctx, now) -> int`, called last in `tick`.

The message format is the spec's 4 lines. The score is shown as `round(score*100)%`. The bids line appears only when the count is known. The link is `<dashboard_url>/lead/<id>`, or `/lead/<id>` when no dashboard_url is set.

- [ ] **Step 1: Write the failing tests.** Fake `send_telegram` with a monkeypatch list.
  - `test_alerts_sends_fresh_reachable_best_first`: three leads at scores 0.9, 0.7 and 0.5 with threshold 0.6 send two messages, 0.9 first.
  - `test_alerts_skip_tagged`: a senior lead with a high score sends nothing.
  - `test_alerts_window`: a lead posted 30 h ago is skipped. A lead with no posted_at and created now is sent.
  - `test_alerts_daily_max`: 8 eligible leads with max 6 send 6. The next tick on the same Tunis day sends 0, and the next day sends 2.
  - `test_alert_not_repeated_after_rescore`: tick, rescore, tick sends 1 in total.
  - `test_alerts_retry_after_error`: when send raises, nothing is marked, and the next tick sends.
  - `test_alerts_disabled_or_unconfigured`: no token, or `alerts_enabled=False`, sends 0 without error.
  - `test_alert_settings_live`: saving `alert_threshold=0.8` on `/settings/schedule` applies without a restart.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Choose the candidates with one SQL query over leads joined to scores: status new, stage1 ≥ threshold, ordered by stage1 descending, limit 50. Filter the window, reach and the alerted list in Python.
  - Mark a lead alerted only after its send succeeds.
  - The settings area "schedule" gets the three fields under an "Alerts" heading. Change its description to "Digest time, instant alerts, follow-ups and when leads expire."
- [ ] **Step 4: Run the suite.** Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(notify): instant Telegram alerts for fresh reachable leads`.

---

### Task 8: Feed sources — We Work Remotely, Jobicy, Golangprojects

**Files:**
- Create: `src/prospector/sources/weworkremotely.py`, `jobicy.py`, `golangprojects.py`, and `tests/fixtures/{weworkremotely,jobicy,golangprojects}/`
- Modify: `src/prospector/sources/adapters.py`
- Test: `tests/sources/test_new_feeds.py`

**Interfaces:**
- Produces:
  - Classes `WeWorkRemotely`, `Jobicy` and `Golangprojects`, with ids `weworkremotely`, `jobicy` and `golangprojects` and `interval_hours` 4, 6 and 6.
  - Each is registered as `register(id)(lambda s, m: Cls())`.

**Fixtures.** Fetch each live endpoint once and save it, trimmed to 3–5 items, as `rss.xml`, or `sample.json` for Jobicy, for one of its tags.

**Mapping.**
- WWR: the title is in the form "Company: Role", so split it on the first ": " into company and title. Use `<guid>` as external_id and `pubDate` as posted_at. `location_text` is `Remote (<region>)`. Fetch all three category feeds and de-duplicate by guid.
- Jobicy: use `id`, `url`, `jobTitle`, `companyName` and `jobDescription`. `location_text` is `Remote (<jobGeo>)`. `pay_text` comes from `annualSalaryMin`, `annualSalaryMax` and `salaryCurrency` when present, formatted as `"<min>-<max> <cur> per year"`. Use `pubDate` as posted_at. Query the tags `golang`, `c++` and `rust`, and de-duplicate by id.
- Golangprojects: use the RSS fields. `location_text` is None, so normalisation decides remote from the text.

- [ ] **Step 1: Write the failing tests.**
  - One parametrised `test_feed_maps_fields`, in the style of `test_job_apis.test_maps_fields`: n leads, titles set, http URLs, a unique external_id, a tz-aware posted_at, and raw_payload set.
  - `test_wwr_splits_company`
  - `test_jobicy_region_and_pay`
  - `test_feeds_empty_ok`: an empty feed or `{"jobs": []}` gives `[]`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** the three adapters and register them.
- [ ] **Step 4: Run the suite.** Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(sources): We Work Remotely, Jobicy, Golangprojects`.

---

### Task 9: TunisieTravail and Codeur

**Files:**
- Create: `src/prospector/sources/tunisietravail.py`, `codeur.py`, and their fixtures
- Modify: `adapters.py`
- Test: `tests/sources/test_local_gigs.py`

**Interfaces:**
- Produces: `TunisieTravail` (id `tunisietravail`, every 6 h) and `Codeur` (id `codeur`, every 6 h, `kind_hint=Kind.GIG`).

**Gate (do this first).** Fetch `https://www.codeur.com/robots.txt` and look for Codeur's terms (CGU) from the site footer. If the terms forbid automated reading or reuse of the listings, skip the Codeur half of this task and ledger it as a ruling: `Ruling: Codeur dropped — <quote of the clause>`.

**Mapping.**
- TunisieTravail:
  - Query each of `développeur`, `developpeur`, `informatique`, `stage` and `pfe`, with `per_page=20` and `_fields=id,date,title,link,excerpt,content`.
  - De-duplicate by id. external_id is `str(id)`. The title is `title.rendered`, HTML-unescaped. The body is `content.rendered`. posted_at is `date` (local time, so treat it as Africa/Tunis). `location_text` is `"Tunisia"`.
  - Skip posts whose title doesn't match `(?i)d[ée]velopp|informati|software|logiciel|stage|pfe|devops|data|web|full ?stack|back ?end|front ?end|ing[ée]nieur`.
- Codeur: RSS. Use the item `link` as the url and the guid or link as external_id. Use `pubDate`. The budget, when the description has `Budget : X € - Y €` or similar, becomes `pay_text` as `"X-Y EUR fixed"`. `location_text` is `"Remote"`.
- Both check `robots_allowed(url, http, USER_AGENT)` before fetching, like Keejob does.

- [ ] **Step 1: Write the failing tests.**
  - `test_tunisietravail_maps_and_filters`: the fixture has one non-tech post, which is dropped.
  - `test_codeur_maps_budget`
  - Empty responses give `[]`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** both adapters and register them.
- [ ] **Step 4: Run the suite.** Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(sources): TunisieTravail and Codeur`.

---

### Task 10: GSoC and Outreachy

**Files:**
- Create: `src/prospector/sources/gsoc.py`, `outreachy.py`, and their fixtures
- Modify: `adapters.py`
- Test: `tests/sources/test_programs.py`

**Interfaces:**
- Produces: `GSoC` (id `gsoc`, every 24 h) and `Outreachy` (id `outreachy`, every 24 h). Both use `kind_hint=Kind.INTERNSHIP` and `location_text="Remote"`.

**Fixtures.**
- GSoC: save `/api/program/` as `programs.json`, and `/api/program/2026/organizations/` trimmed to 5 orgs (at least 2 with c, c++ or go tags, and 1 without) as `orgs.json`.
- Outreachy: save the project-selection page trimmed to 3 project blocks as `projects.html`.

**Mapping.**
- GSoC:
  - Pick the program with the latest `contributor_application_deadline`, or the closest equivalent key in the fixture (record the key you find), that is still after now. If none is, return `[]`.
  - Keep orgs whose `tech_tags`, lower-cased, intersect {c, c++, go, golang}.
  - Each org becomes a lead: title `GSoC <year>: <name>`, url `https://summerofcode.withgoogle.com/programs/<year>/organizations/<slug>`, body = description plus `Tech: <tags>`, deadline = the deadline date, external_id `<year>:<slug>`.
  - Any KeyError or TypeError logs a warning and returns `[]`.
  - `fetch` takes `now` from `datetime.now(UTC)`. Tests monkeypatch a module-level `_now()`.
- Outreachy:
  - Parse with selectolax. Each project block gives title, community, skills text and url. The deadline comes from the page's "Final Applications Due <Month D, YYYY>".
  - external_id is the url. With no blocks, it returns `[]` and logs a warning.

- [ ] **Step 1: Write the failing tests.**
  - `test_gsoc_open_program_filters_tags`: with now before the deadline, it returns 2 leads with the internship kind hint and the deadline set.
  - `test_gsoc_closed_program_empty`: with now after the deadline, it returns `[]`.
  - `test_gsoc_bad_shape_empty`: `{"weird": 1}` gives `[]`.
  - `test_outreachy_parses_projects`
  - `test_outreachy_no_blocks_empty`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** both adapters and register them.
- [ ] **Step 4: Run the suite.** Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(sources): Google Summer of Code and Outreachy`.

---

### Task 11: Defaults and the sources page

**Files:**
- Modify: `src/prospector/config.py` (`enabled_sources` default), `tests/sources/test_registry.py`
- Test: `tests/sources/test_registry.py`

- [ ] **Step 1: Write the failing test.** `test_new_sources_registered_and_default`: `known_source_ids()` includes all seven new ids, or six if Codeur was dropped in Task 9, and `Settings(profile_path=...).enabled_sources` includes them.
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Implement.** Append the new ids to the default after `keejob`.
- [ ] **Step 4: Run the full suite.** Expected: PASS, with all tests green.
- [ ] **Step 5: Commit** with message `feat(sources): enable the new sources by default`.

---

## Deploy (after merge, not a task)

1. On the server, back up `data/profile.yaml`, `data/settings.json` and `data/prospector.db` to `*.pre-reach`.
2. Set `targets.levels: [intern, junior]` in `data/profile.yaml`, and add the new ids to `enabled_sources` in `data/settings.json`.
3. Run `git pull && sudo docker compose up -d --build`, then re-score from Settings.
4. Re-run the top-100 count (senior titles, ≥4 years, region-locked) and report the before (43 / 30 / 11) and after numbers.
