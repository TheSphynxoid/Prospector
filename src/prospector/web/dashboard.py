import hashlib
import math
import json
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from prospector.assist.usage import used_today
from prospector import fx
from prospector.config import parse_hhmm
from prospector.context import AppContext
from prospector.models import Kind, Remote, Status
from prospector.sources.registry import known_source_ids
from prospector.store.stats import TZ, StatsRepo
from prospector.web.checklist import EXAMPLE_PROFILE, setup_items
from prospector.web.format import fmt_ago, fmt_pay, paragraphs
from prospector.worklife.flows import on_applied, on_unapplied

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
PAGE_SIZE = 50
_ACTIONS = {"star": Status.STARRED, "dismiss": Status.DISMISSED, "applied": Status.APPLIED, "reset": Status.NEW}
_TOAST = {"star": "Starred", "dismiss": "Dismissed", "applied": "Marked applied · tracking in Work",
          "reset": "Moved back to new"}
TABS = [Status.NEW, Status.STARRED, Status.APPLIED, Status.FILTERED, Status.EXPIRED, Status.DISMISSED]


def next_digest(now: datetime, at: time) -> datetime:
    local = now.astimezone(TZ)
    nxt = datetime.combine(local.date(), at, TZ)
    if nxt <= local:
        nxt += timedelta(days=1)
    return nxt.astimezone(UTC)


def _local(ts: datetime | str | None) -> str:
    if not ts:
        return "never"
    dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    return dt.astimezone(TZ).strftime("%a %d %b, %H:%M")


templates.env.filters["local"] = _local
# Cache-buster for /static links: changes whenever app.css or app.js does, so a deploy is picked up at once.
_STATIC = Path(__file__).parent / "static"
templates.env.globals["asset_v"] = hashlib.sha256(
    b"".join((_STATIC / f).read_bytes() for f in ("app.css", "app.js"))).hexdigest()[:10]
templates.env.filters["pay"] = fmt_pay
templates.env.filters["ago"] = lambda ts: fmt_ago(ts, datetime.now(UTC))
templates.env.filters["paragraphs"] = paragraphs


def _enum(cls, value: str):
    try:
        return cls(value.strip()) if value.strip() else None
    except ValueError:
        return None


def _score(value: str) -> float | None:
    try:
        x = float(value)
    except ValueError:
        return None
    return min(max(x, 0.0), 1.0) if math.isfinite(x) else None


def make_dashboard_router(ctx: AppContext) -> APIRouter:
    router = APIRouter()
    stats = StatsRepo(ctx.conn)

    @router.get("/")
    def overview(request: Request):
        from prospector.web.work import work_tile  # web.work imports this module's templates
        if "tab" in request.query_params:  # old list links and bookmarks
            return RedirectResponse(f"/leads?{request.query_params}", status_code=307)
        now = datetime.now(UTC)
        return templates.TemplateResponse(request, "overview.html", {
            "nav": "overview", "o": stats.overview(now), "cap": ctx.settings.llm_daily_cap,
            "assistant_used": used_today(ctx), "assistant_cap": ctx.settings.assistant_daily_cap,
            "top": ctx.leads.list(Status.NEW, limit=5),
            "last_digest": ctx.kv.get("last_digest_at"), "next_digest": next_digest(now, parse_hhmm(ctx.settings.digest_time)),
            "sources": ctx.health.all(), "needs_you": ctx.mail.needs_you(),
            "setup": setup_items(ctx.settings, ctx.kv, ctx.settings.profile_path, EXAMPLE_PROFILE),
            "work": work_tile(ctx),
        })

    @router.get("/leads")
    def leads(request: Request, tab: str = "", kind: str = "", remote: str = "", source: str = "",
              min_score: str = "", sort: str = "score", page: str = "1", q: str | None = None):
        # The filter form sends "" for "Any"; a bad value in a hand-edited URL falls back instead of a 422.
        tab = _enum(Status, tab) or Status.NEW
        kind, remote = _enum(Kind, kind), _enum(Remote, remote)
        source = source.strip() or None
        min_score = _score(min_score)
        sort = sort if sort in ("score", "date") else "score"
        page = max(int(page), 1) if page.strip().lstrip("-").isdigit() else 1
        rows = ctx.leads.list(tab, kind=kind, remote=remote, source=source or None, min_score=min_score,
                              sort=sort, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE, q=q)
        filters = {"q": (q or "").strip() or None, "kind": kind, "remote": remote, "source": source,
                   "min_score": min_score, "sort": sort}
        kept = urlencode({k: getattr(v, "value", v) for k, v in filters.items()
                          if v not in (None, "") and not (k == "sort" and v == "score")})
        query = f"tab={tab.value}" + (f"&{kept}" if kept else "")
        filtering = any(filters[k] not in (None, "") for k in ("kind", "remote", "source", "min_score"))
        return templates.TemplateResponse(request, "list.html", {
            "nav": "leads", "rows": rows, "tab": tab, "tabs": TABS, "kinds": list(Kind), "remotes": list(Remote),
            "filters": filters, "query": query, "kept": kept, "filtering": filtering, "sources": known_source_ids(),
            "page": page, "has_next": len(rows) == PAGE_SIZE,
            "needs_you": ctx.mail.needs_you(), "paused": [h for h in ctx.health.all() if h.paused],
        })

    @router.get("/lead/{lead_id}")
    def detail(request: Request, lead_id: int):
        row = ctx.leads.get_row(lead_id)
        if row is None:
            raise HTTPException(404)
        from prospector.web.assist import assist_context  # web.assist imports this module's templates
        return templates.TemplateResponse(request, "detail.html", {
            "nav": "leads", "row": row, "breakdown": ctx.scores.breakdown(lead_id) or {}, "lead_id": lead_id,
            "application": ctx.apps.by_lead(lead_id),
            **assist_context(ctx, lead_id),
        })

    def fragment(request: Request, lead_id: int, headers: dict | None = None):
        # The detail page swaps its action bar; lists swap the whole row.
        name = "_detail_actions.html" if request.headers.get("hx-target") == "detail-actions" else "_row.html"
        return templates.TemplateResponse(request, name, {"row": ctx.leads.get_row(lead_id),
                                                          "application": ctx.apps.by_lead(lead_id)}, headers=headers)

    @router.post("/lead/{lead_id}/undo")
    def undo(request: Request, lead_id: int, to: Status, fb: int):
        lead = ctx.leads.get(lead_id)
        if lead is None:
            raise HTTPException(404)
        if lead.status == Status.APPLIED and to != Status.APPLIED:
            on_unapplied(ctx, lead_id)
        ctx.leads.set_status(lead_id, to)
        ctx.feedback.delete(fb, lead_id)  # so undo does not train the ranker
        return fragment(request, lead_id)

    @router.post("/lead/{lead_id}/still-open")
    def still_open(request: Request, lead_id: int):
        """The "may have closed" badge was wrong: drop it and don't raise that reason again."""
        if ctx.leads.get(lead_id) is None:
            raise HTTPException(404)
        ctx.expiry.keep_open(lead_id)
        return fragment(request, lead_id)

    @router.post("/lead/{lead_id}/{action}")
    def act(request: Request, lead_id: int, action: str):
        status = _ACTIONS.get(action)
        lead = ctx.leads.get(lead_id)
        if status is None or lead is None:
            raise HTTPException(404)
        previous = lead.status
        if action == "reset":  # back to new means "still open": don't expire it again for the same reason
            ctx.expiry.keep_open(lead_id)
        ctx.leads.set_status(lead_id, status)
        if action == "applied":
            on_applied(ctx, lead_id, fx.today())
        fb = ctx.feedback.record(lead_id, action)
        target = "#detail-actions" if request.headers.get("hx-target") == "detail-actions" else f"#lead-{lead_id}"
        trigger = {"toast": {"msg": _TOAST[action], "target": target,
                             "undo": f"/lead/{lead_id}/undo?{urlencode({'to': previous.value, 'fb': fb})}"}}
        return fragment(request, lead_id, {"HX-Trigger": json.dumps(trigger)})

    @router.get("/health")
    def health():
        return RedirectResponse("/settings/sources", status_code=303)  # old digest links

    @router.post("/needs-you/{item_id}/dismiss")
    def dismiss_needs_you(item_id: int):
        ctx.mail.dismiss_needs_you(item_id)
        return ""

    return router
