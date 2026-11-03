"""The lead page's assistant card: chat, one-click bid and the full posting."""
from fastapi import APIRouter, Form, HTTPException, Request

from prospector.assist.bid import draft_bid
from prospector.assist.chat import send
from prospector.assist.fetch import refresh_posting
from prospector.context import AppContext
from prospector.store.assist import Message
from prospector.web.dashboard import templates

PASTE_LIMIT = 20000


def assist_context(ctx: AppContext, lead_id: int) -> dict:
    """What _assist.html needs; starts the one-time posting fetch in the background."""
    row = ctx.assist.get(lead_id)
    if not row.fetch_tried:
        ctx.run_background(lambda: refresh_posting(ctx, lead_id))
        row = ctx.assist.get(lead_id)
    return {"assist": row, "messages": ctx.assist.messages(lead_id), "bid": row.bid,
            "usd_tnd": ctx.settings.usd_tnd_rate}


def make_assist_router(ctx: AppContext) -> APIRouter:
    router = APIRouter(prefix="/lead/{lead_id}/assist")

    def lead_or_404(lead_id: int):
        lead = ctx.leads.get(lead_id)
        if lead is None:
            raise HTTPException(404)
        return lead

    def render(request: Request, name: str, lead_id: int, **extra):
        return templates.TemplateResponse(request, name, {"lead_id": lead_id, "assist": ctx.assist.get(lead_id),
                                                          "usd_tnd": ctx.settings.usd_tnd_rate, **extra})

    @router.get("/posting-status")
    def posting_status(request: Request, lead_id: int):
        lead_or_404(lead_id)
        return render(request, "_assist_posting.html", lead_id)

    @router.post("/posting")
    def paste(request: Request, lead_id: int, posting: str = Form("")):
        lead_or_404(lead_id)
        if posting.strip():
            ctx.assist.set_posting(lead_id, posting.strip()[:PASTE_LIMIT], "pasted")
        return render(request, "_assist_posting.html", lead_id)

    @router.post("/fetch")
    def fetch(request: Request, lead_id: int):
        lead_or_404(lead_id)
        refresh_posting(ctx, lead_id)  # the owner asked and waits; 10 s timeout per hop
        return render(request, "_assist_posting.html", lead_id)

    @router.post("/message")
    def message(request: Request, lead_id: int, text: str = Form("")):
        lead_or_404(lead_id)
        new = send(ctx, lead_id, text.strip()) if text.strip() else []
        return render(request, "_assist_messages.html", lead_id, messages=new)

    @router.post("/bid")
    def bid(request: Request, lead_id: int):
        lead_or_404(lead_id)
        out = draft_bid(ctx, lead_id)
        error = out.content if isinstance(out, Message) else None
        summary = [] if error else ctx.assist.messages(lead_id)[-1:]
        return render(request, "_assist_bid.html", lead_id, bid=ctx.assist.get(lead_id).bid, error=error,
                      oob_messages=summary)

    @router.post("/clear")
    def clear(request: Request, lead_id: int):
        lead_or_404(lead_id)
        ctx.assist.clear(lead_id)
        return render(request, "_assist_cleared.html", lead_id)

    return router
