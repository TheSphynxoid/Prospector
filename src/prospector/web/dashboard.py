from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from prospector.config import parse_hhmm
from prospector.context import AppContext
from prospector.models import Kind, Remote, Status
from prospector.store.stats import TZ, StatsRepo
from prospector.web.checklist import EXAMPLE_PROFILE, setup_items

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
PAGE_SIZE = 50
_ACTIONS = {"star": Status.STARRED, "dismiss": Status.DISMISSED, "applied": Status.APPLIED, "reset": Status.NEW}
TABS = [Status.NEW, Status.STARRED, Status.APPLIED, Status.FILTERED, Status.DISMISSED]


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


def make_dashboard_router(ctx: AppContext) -> APIRouter:
    router = APIRouter()
    stats = StatsRepo(ctx.conn)

    @router.get("/")
    def overview(request: Request):
        if "tab" in request.query_params:  # old list links and bookmarks
            return RedirectResponse(f"/leads?{request.query_params}", status_code=307)
        now = datetime.now(UTC)
        return templates.TemplateResponse(request, "overview.html", {
            "nav": "overview", "o": stats.overview(now), "cap": ctx.settings.llm_daily_cap,
            "top": ctx.leads.list(Status.NEW, limit=5),
            "last_digest": ctx.kv.get("last_digest_at"), "next_digest": next_digest(now, parse_hhmm(ctx.settings.digest_time)),
            "sources": ctx.health.all(), "needs_you": ctx.mail.needs_you(),
            "setup": setup_items(ctx.settings, ctx.kv, ctx.settings.profile_path, EXAMPLE_PROFILE),
        })

    @router.get("/leads")
    def leads(request: Request, tab: Status = Status.NEW, kind: Kind | None = None, remote: Remote | None = None,
              source: str | None = None, min_score: float | None = None, sort: str = "score", page: int = 1):
        sort = sort if sort in ("score", "date") else "score"
        page = max(page, 1)
        rows = ctx.leads.list(tab, kind=kind, remote=remote, source=source or None, min_score=min_score,
                              sort=sort, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
        filters = {"kind": kind, "remote": remote, "source": source, "min_score": min_score, "sort": sort}
        query = urlencode({"tab": tab.value, **{k: getattr(v, "value", v) for k, v in filters.items()
                                                 if v not in (None, "")}})
        return templates.TemplateResponse(request, "list.html", {
            "nav": "leads", "rows": rows, "tab": tab, "tabs": TABS, "kinds": list(Kind), "remotes": list(Remote),
            "filters": filters, "query": query, "page": page, "has_next": len(rows) == PAGE_SIZE,
            "needs_you": ctx.mail.needs_you(), "paused": [h for h in ctx.health.all() if h.paused],
        })

    @router.get("/lead/{lead_id}")
    def detail(request: Request, lead_id: int):
        row = ctx.leads.get_row(lead_id)
        if row is None:
            raise HTTPException(404)
        return templates.TemplateResponse(request, "detail.html", {
            "nav": "leads", "row": row, "breakdown": ctx.scores.breakdown(lead_id) or {},
        })

    @router.post("/lead/{lead_id}/{action}")
    def act(request: Request, lead_id: int, action: str):
        status = _ACTIONS.get(action)
        if status is None or ctx.leads.get(lead_id) is None:
            raise HTTPException(404)
        ctx.leads.set_status(lead_id, status)
        ctx.feedback.record(lead_id, action)
        return templates.TemplateResponse(request, "_row.html", {"row": ctx.leads.get_row(lead_id)})

    @router.get("/health")
    def health(request: Request):
        return templates.TemplateResponse(request, "health.html", {"nav": "health", "sources": ctx.health.all()})

    @router.post("/needs-you/{item_id}/dismiss")
    def dismiss_needs_you(item_id: int):
        ctx.mail.dismiss_needs_you(item_id)
        return ""

    return router
