"""Lead expiry: deadlines, closed on the source, too old, or the page is gone.

New and filtered leads move to the Expired tab; starred and applied leads only get a "may have closed" badge,
since the owner is already working on them. Nothing is deleted, and a reason the owner overrode is never
raised again for that lead.
"""
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from prospector.assist.fetch import page_gone
from prospector.config import Settings
from prospector.context import AppContext
from prospector.models import Kind, Lead, Status

log = logging.getLogger(__name__)

FREELANCER_API = "https://www.freelancer.com/api/projects/0.1/projects/"
_GITHUB_ISSUE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/issues/(\d+)")
OPEN_STATES = (Status.NEW, Status.FILTERED, Status.STARRED, Status.APPLIED)
GITHUB_MAX = 100  # API calls per run


@dataclass(frozen=True)
class Signal:
    key: str     # deadline | freelancer | github | age | gone — an override ignores the key, not the wording
    reason: str


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def deadline_signal(lead: Lead, now: datetime) -> Signal | None:
    if lead.deadline and lead.deadline < now.date():
        return Signal("deadline", f"Deadline passed ({lead.deadline.isoformat()}).")
    return None


def max_age_days(kind: Kind, s: Settings) -> int:
    if kind in (Kind.GIG, Kind.BOUNTY):
        return s.expire_days_short
    if kind in (Kind.JOB, Kind.CONTRACT):
        return s.expire_days_jobs
    return s.expire_days_long


def age_signal(lead: Lead, created_at: str | None, now: datetime, s: Settings) -> Signal | None:
    when, label = (lead.posted_at, "Posted") if lead.posted_at else (
        datetime.fromisoformat(created_at) if created_at else None, "First seen")
    if when is None:
        return None
    days = (now - _aware(when)).days
    if days > max_age_days(lead.kind, s):
        return Signal("age", f"{label} {days} days ago.")
    return None


def _open_leads(ctx: AppContext, source: str | None = None) -> list[tuple[int, Lead, str | None]]:
    marks = ",".join("?" * len(OPEN_STATES))
    sql = f"SELECT id, created_at FROM leads WHERE status IN ({marks})"
    args: list = [s.value for s in OPEN_STATES]
    if source:
        sql += " AND EXISTS (SELECT 1 FROM json_each(sources) WHERE value = ?)"
        args.append(source)
    out = []
    for r in ctx.conn.execute(sql, args).fetchall():
        lead = ctx.leads.get(r["id"])
        if lead:
            out.append((r["id"], lead, r["created_at"]))
    return out


def check_freelancer(ctx: AppContext, http: httpx.Client) -> Iterable[tuple[int, Signal]]:
    leads = [lid for lid, _, _ in _open_leads(ctx, "freelancer")]
    refs = ctx.expiry.refs("freelancer", leads)
    by_ext = {ext: lid for lid, ext in refs.items()}
    exts = list(by_ext)
    for i in range(0, len(exts), 50):
        batch = exts[i:i + 50]
        try:
            resp = http.get(FREELANCER_API, params=[("projects[]", e) for e in batch], timeout=20)
            resp.raise_for_status()
            projects = resp.json().get("result", {}).get("projects", [])
        except (httpx.HTTPError, ValueError) as e:
            log.warning("freelancer closed check failed: %s", e)
            continue
        for p in projects:
            lid = by_ext.get(str(p.get("id")))
            if lid is None:
                continue
            if p.get("status") not in (None, "active"):
                yield lid, Signal("freelancer", "Closed on Freelancer.")
            elif p.get("frontend_project_status") in ("work_in_progress", "complete"):
                yield lid, Signal("freelancer", "Awarded on Freelancer.")


def check_github(ctx: AppContext, http: httpx.Client, token: str) -> Iterable[tuple[int, Signal]]:
    calls = 0
    for lid, lead, _ in _open_leads(ctx, "github_bounties"):
        m = _GITHUB_ISSUE.match(lead.canonical_url)
        if not m or calls >= GITHUB_MAX:
            continue
        calls += 1
        try:
            resp = http.get(f"https://api.github.com/repos/{m[1]}/{m[2]}/issues/{m[3]}", timeout=20,
                            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
            resp.raise_for_status()
            state = resp.json().get("state")
        except (httpx.HTTPError, ValueError) as e:
            log.warning("github closed check failed for lead %s: %s", lid, e)
            continue
        if state == "closed":
            yield lid, Signal("github", "Issue closed on GitHub.")


def _apply(ctx: AppContext, lead_id: int, status: Status, sig: Signal) -> bool:
    if sig.key in ctx.expiry.ignored(lead_id):
        return False
    if status in (Status.NEW, Status.FILTERED):
        ctx.conn.execute("UPDATE leads SET status = ? WHERE id = ?", (Status.EXPIRED.value, lead_id))
        ctx.expiry.flag(lead_id, sig.key, sig.reason)
        return True
    if status in (Status.STARRED, Status.APPLIED) and ctx.expiry.flagged_key(lead_id) != sig.key:
        ctx.expiry.flag(lead_id, sig.key, sig.reason)
        return True
    return False


def run_expiry(ctx: AppContext, now: datetime) -> int:
    """Daily pass. Returns how many leads were expired or newly flagged."""
    leads = {lid: (lead, created) for lid, lead, created in _open_leads(ctx)}
    sources: dict[int, Signal] = {}
    try:
        checks = list(check_freelancer(ctx, ctx.http))
        if ctx.settings.github_token:
            checks += list(check_github(ctx, ctx.http, ctx.settings.github_token.get_secret_value()))
        sources = dict(checks)
    except Exception:  # noqa: BLE001 — a broken source check must not stop the local rules
        log.exception("source closed checks failed")
    changed = 0
    for lid, (lead, created) in leads.items():
        ignored = ctx.expiry.ignored(lid)
        # strongest first; a reason the owner overrode doesn't hide the next one
        for sig in (deadline_signal(lead, now), sources.get(lid), age_signal(lead, created, now, ctx.settings)):
            if sig and sig.key not in ignored:
                changed += _apply(ctx, lid, lead.status, sig)
                break
    log.info("expiry: %d leads expired or flagged", changed)
    return changed


def check_links(ctx: AppContext, now: datetime) -> int:
    """Weekly: flag starred/applied leads whose posting page now answers 404/410."""
    changed = 0
    for status in (Status.STARRED, Status.APPLIED):
        for row in ctx.leads.list(status, limit=500):
            try:
                gone = page_gone(row.lead.canonical_url)
            except Exception:  # noqa: BLE001
                log.exception("link check failed for lead %s", row.lead.id)
                continue
            if gone:
                changed += _apply(ctx, row.lead.id, status, Signal("gone", "The posting page is gone (404)."))
    return changed
