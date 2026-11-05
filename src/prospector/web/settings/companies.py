"""Settings → Companies: the career boards Prospector watches, added by discovery or by pasting a link."""
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from prospector.companies.boards import LABEL, parse_board_url
from prospector.companies.discover import discover, is_running
from prospector.context import AppContext
from prospector.search.client import search_ready
from prospector.store.companies import STATES
from prospector.web.dashboard import templates

FILTERS = ("all", "watching", "muted", "paused")
NO_SEARCH = "Set up web search in Settings → Connections"
_AREA = SimpleNamespace(key="companies", title="Companies")


def _backoff(ctx: AppContext) -> datetime | None:
    until = ctx.kv.get("discover_backoff_until")
    if not until:
        return None
    dt = datetime.fromisoformat(until)
    return dt if dt > datetime.now(UTC) else None


def make_companies_router(ctx: AppContext) -> APIRouter:
    router = APIRouter(prefix="/settings/companies")

    def page(request: Request, state: str = "all", notice: str = "", error: str = "", status: int = 200):
        from prospector.web.settings.pages import AREAS
        state = state if state in FILTERS else "all"
        return templates.TemplateResponse(request, "settings/companies.html", {
            "nav": "settings", "area": _AREA, "areas": AREAS, "errors": {}, "notice": notice, "error": error,
            "companies": ctx.companies.list(None if state == "all" else state), "counts": ctx.companies.counts(),
            "filter": state, "filters": FILTERS, "labels": LABEL, "search_ready": search_ready(ctx),
            "no_search": NO_SEARCH, "last": ctx.kv.get("discover_last"), "backoff": _backoff(ctx),
            "running": is_running(),
        }, status_code=status)

    @router.get("")
    def show(request: Request, state: str = "all", started: str = ""):
        notice = "Discovery started — new companies appear here in a few minutes" if started else ""
        return page(request, state, notice=notice)

    @router.post("/add")
    async def add(request: Request):
        url = str((await request.form()).get("url") or "")
        parsed = parse_board_url(url)
        if parsed is None:
            return page(request, error="Not a Greenhouse, Lever or Ashby link", status=400)
        board, token = parsed
        if not ctx.companies.add(board, token, found_by="added by you"):
            return page(request, notice="Already watched")
        added = next(c for c in ctx.companies.list() if (c.board, c.token) == parsed)
        return page(request, notice=f"Added {added.display_name} ({LABEL[board]})")

    @router.post("/{company_id}/state")
    async def set_state(request: Request, company_id: int):
        state = str((await request.form()).get("state") or "")
        company = ctx.companies.get(company_id)
        if company is None:
            raise HTTPException(404)
        if state not in STATES:
            return page(request, error="Unknown state", status=400)
        ctx.companies.set_state(company_id, state)
        verb = {"watching": "Watching", "muted": "Muted", "paused": "Paused"}[state]
        return page(request, notice=f"{verb} {company.display_name}")

    @router.post("/discover")
    def discover_now(request: Request):
        if not search_ready(ctx):
            return page(request, error=NO_SEARCH, status=400)
        if is_running():
            return page(request, notice="Discovery is already running")
        ctx.run_background(lambda: discover(ctx, datetime.now(UTC), manual=True))
        return RedirectResponse("/settings/companies?started=1", status_code=303)  # a refresh doesn't start another

    return router
