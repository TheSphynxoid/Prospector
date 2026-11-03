from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from prospector.context import AppContext
from prospector.models import Kind, Remote, Status

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
PAGE_SIZE = 50
_ACTIONS = {"star": Status.STARRED, "dismiss": Status.DISMISSED, "applied": Status.APPLIED, "reset": Status.NEW}
TABS = [Status.NEW, Status.STARRED, Status.APPLIED, Status.FILTERED, Status.DISMISSED]


def make_dashboard_router(ctx: AppContext) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    def index(request: Request, tab: Status = Status.NEW, kind: Kind | None = None, remote: Remote | None = None,
              source: str | None = None, min_score: float | None = None, sort: str = "score", page: int = 1):
        sort = sort if sort in ("score", "date") else "score"
        rows = ctx.leads.list(tab, kind=kind, remote=remote, source=source or None, min_score=min_score,
                              sort=sort, limit=PAGE_SIZE, offset=(max(page, 1) - 1) * PAGE_SIZE)
        paused = [h for h in ctx.health.all() if h.paused]
        return templates.TemplateResponse(request, "list.html", {
            "rows": rows, "tab": tab, "tabs": TABS, "kinds": list(Kind), "remotes": list(Remote),
            "filters": {"kind": kind, "remote": remote, "source": source, "min_score": min_score, "sort": sort},
            "page": page, "has_next": len(rows) == PAGE_SIZE,
            "needs_you": ctx.mail.needs_you(), "paused": paused,
        })

    @router.get("/lead/{lead_id}")
    def detail(request: Request, lead_id: int):
        row = ctx.leads.get_row(lead_id)
        if row is None:
            raise HTTPException(404)
        return templates.TemplateResponse(request, "detail.html", {
            "row": row, "breakdown": ctx.scores.breakdown(lead_id) or {},
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
        return templates.TemplateResponse(request, "health.html", {"sources": ctx.health.all()})

    @router.post("/needs-you/{item_id}/dismiss")
    def dismiss_needs_you(item_id: int):
        ctx.mail.dismiss_needs_you(item_id)
        return ""

    return router
