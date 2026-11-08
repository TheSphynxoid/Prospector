"""Read-only JSON for agents (and scripts): ranked leads with filters, one lead in full, the source ids.

Same access rule as the dashboard (tailnet, or Cloudflare Access). Nothing here changes data. Bad filter
values are a 422 that says what is allowed, never a silent fallback: a caller should know its filter applied.
"""
import re
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from prospector.context import AppContext
from prospector.models import Kind, Remote, Status
from prospector.sources.registry import known_source_ids
from prospector.store.leads import LeadRow
from prospector.web.format import fmt_pay

MAX_LIMIT = 200
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DAYS = re.compile(r"^(\d{1,4})d$")


def _now() -> datetime:
    return datetime.now(UTC)


def _since(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    value = value.strip()
    if m := _DAYS.match(value):
        return _now() - timedelta(days=int(m[1]))
    try:
        return datetime.combine(date.fromisoformat(value), datetime.min.time(), UTC)
    except ValueError:
        raise HTTPException(422, f"since must be a date (2026-11-01) or a number of days (7d), not {value!r}")


def _emails(text: str) -> list[str]:
    return list(dict.fromkeys(m.rstrip(".") for m in _EMAIL.findall(text or "")))


def _summary(row: LeadRow) -> dict:
    lead, review = row.lead, row.stage2 or {}
    return {
        "id": lead.id, "title": lead.title, "company": lead.company, "kind": lead.kind.value,
        "status": lead.status.value, "remote": lead.remote.value, "locations": lead.locations,
        "pay": fmt_pay(lead.pay), "posted_at": lead.posted_at.isoformat() if lead.posted_at else None,
        "first_seen": row.created_at, "deadline": lead.deadline.isoformat() if lead.deadline else None,
        "sources": lead.sources, "score": row.stage1, "verdict": review.get("verdict"),
        "fit_summary": review.get("fit_summary"), "emails": _emails(lead.body), "url": lead.canonical_url,
        "api_url": f"/api/leads/{lead.id}", "closed_reason": row.closed_reason,
    }


def make_api_router(ctx: AppContext) -> APIRouter:
    router = APIRouter(prefix="/api")

    def check_sources(names: list[str]) -> list[str]:
        known = known_source_ids()
        bad = [n for n in names if n not in known]
        if bad:
            raise HTTPException(422, f"unknown source {', '.join(bad)}; known: {', '.join(known)}")
        return list(dict.fromkeys(names))

    @router.get("/leads")
    def leads(status: Status = Status.NEW, source: list[str] = Query([]), not_source: list[str] = Query([]),
              kind: list[Kind] = Query([]), remote: Remote | None = None,
              min_score: float | None = Query(None, ge=0, le=1), q: str | None = None,
              location: str | None = None, since: str | None = None,
              verdict: Literal["strong", "maybe", "weak"] | None = None, has_email: bool = False,
              sort: Literal["score", "date"] = "score", limit: int = Query(50, ge=1, le=MAX_LIMIT),
              offset: int = Query(0, ge=0)):
        filters = dict(kind=kind, remote=remote, source=check_sources(source),
                       skip_sources=check_sources(not_source), min_score=min_score, q=q, location=location,
                       since=_since(since), verdict=verdict, has_email=has_email, deep=True)
        rows = ctx.leads.list(status, sort=sort, limit=limit, offset=offset, **filters)
        return {"total": ctx.leads.count(status, **filters), "limit": limit, "offset": offset,
                "leads": [_summary(r) for r in rows]}

    @router.get("/leads/{lead_id}")
    def lead(lead_id: int):
        row = ctx.leads.get_row(lead_id)
        if row is None:
            raise HTTPException(404, "no such lead")
        assist = ctx.assist.get(lead_id)  # the page text, if the assistant fetched or you pasted it
        app = ctx.apps.by_lead(lead_id)
        return jsonable_encoder({
            **_summary(row), "body": assist.posting or row.lead.body,
            "posting_origin": assist.posting_origin if assist.posting else "source",
            "languages": row.lead.languages, "filter_reason": row.lead.filter_reason,
            "breakdown": ctx.scores.breakdown(lead_id), "review": row.stage2, "bid": assist.bid,
            "application": asdict(app) if app else None, "dashboard_url": f"/lead/{lead_id}",
        })

    @router.get("/sources")
    def sources():
        enabled = set(ctx.settings.enabled_sources)
        return {"sources": [{"id": s, "enabled": s in enabled} for s in known_source_ids()]}

    return router
