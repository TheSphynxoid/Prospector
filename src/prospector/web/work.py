"""The Work area: applications and follow-ups, won work, payments, accounts and money."""
import json
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from prospector import fx
from prospector.context import AppContext
from prospector.fx import CURRENCIES
from prospector.models import Kind
from prospector.money import fmt, parse_amount
from prospector.store.applications import CLOSED_STAGES, STAGES
from prospector.store.works import ACTIVE_STAGES
from prospector.web.dashboard import templates
from prospector.worklife import followups

PAGE_SIZE = 50
_ACT_TOAST = {"followed_up": "Followed up · next reminder in {days} days", "interview": "Next step saved",
              "snooze": "Snoozed", "won": "Won", "rejected": "Marked rejected", "no_reply": "Marked no reply",
              "withdrawn": "Withdrawn"}
STAGE_LABEL = {"waiting": "Waiting", "interview": "Interview", "won": "Won", "rejected": "Rejected",
               "no_reply": "No reply", "withdrawn": "Withdrawn", "in_progress": "In progress",
               "delivered": "Delivered", "closed": "Closed", "cancelled": "Cancelled"}
templates.env.filters["money"] = fmt
templates.env.globals["stage_label"] = lambda s: STAGE_LABEL.get(s, s)


def parse_day(raw: str | None, default: date | None = None) -> date | None:
    """A date from a form field; blank gives the default. Raises ValueError for anything else."""
    raw = (raw or "").strip()
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Use a date like 2026-11-04.") from None


def _int(raw: str, default: int = 1) -> int:
    raw = (raw or "").strip()
    return max(int(raw), 1) if raw.isdigit() else default


def toast(msg: str, undo: str | None = None) -> dict:
    t = {"msg": msg}
    if undo:
        t["undo"] = undo
    return {"HX-Trigger": json.dumps({"toast": t})}


def make_work_router(ctx: AppContext) -> APIRouter:
    router = APIRouter(prefix="/work")
    rates = ctx.fx

    def usd(milli: int, code: str, day: date | None = None) -> int:
        return rates.convert(milli, code, "USD", day)

    def tnd(usd_milli: int) -> str:
        whole = round(rates.convert(usd_milli, "USD", "TND") / 1000) * 1000
        return f"≈ {fmt(whole, 'TND')}"

    templates.env.filters["tnd"] = tnd

    def render(request: Request, name: str, data: dict, status: int = 200, headers: dict | None = None):
        return templates.TemplateResponse(request, name, {"nav": "work", **data}, status_code=status, headers=headers)

    # Overview

    def work_rows(works):
        rows = []
        for w in works:
            paid = ctx.works.paid_usd_milli(w.id)
            price = usd(w.price_milli, w.currency) if w.price_milli else None
            pct = min(100, round(paid * 100 / price)) if price else None
            rows.append({"w": w, "paid": paid, "price": price, "pct": pct})
        return rows

    def overview_data() -> dict:
        today = fx.today()
        received = ctx.works.received_between(today.replace(day=1), today)
        expected = ctx.works.expected()
        accounts = ctx.accounts.list()
        totals = ctx.accounts.received_totals()
        return {
            "today": today,
            "received_usd": sum(p.usd_milli or 0 for p in received),
            "expected_usd": sum(usd(p.amount_milli, p.currency) for p in expected),
            "expected_week": sum(1 for p in expected if p.due_on and p.due_on <= today + timedelta(days=7)),
            "active": work_rows(ctx.works.list(stages=ACTIVE_STAGES)),
            "counts": ctx.apps.counts_since(today - timedelta(days=30)),
            "due": followups.due(ctx.apps, today),
            "pipeline": [
                ("Waiting", "waiting", ctx.apps.list(stage="waiting", limit=3)),
                ("Interview", "interview", ctx.apps.list(stage="interview", limit=3)),
                ("Won", "won", ctx.apps.list(stage="won", limit=3)),
                ("Closed", "closed", ctx.apps.list(stages=CLOSED_STAGES, limit=3)),
            ],
            "stage_counts": ctx.apps.stage_counts(),
            "accounts": [(a, totals.get(a.id, 0), usd(totals.get(a.id, 0), a.currency)) for a in accounts],
            "empty": not ctx.apps.list(limit=1) and not ctx.works.list(limit=1),
        }

    @router.get("")
    def overview(request: Request):
        return render(request, "work/overview.html", {"tab": "overview", **overview_data()})

    # Applications

    def app_or_404(app_id: int):
        a = ctx.apps.get(app_id)
        if a is None:
            raise HTTPException(404)
        return a

    def panel(request: Request, app_id: int, status: int = 200, error: str = "", headers: dict | None = None):
        a = ctx.apps.get(app_id)
        return render(request, "work/_app_panel.html", {
            "a": a, "events": ctx.apps.events(app_id), "work": ctx.works.by_application(app_id),
            "error": error, "today": fx.today()}, status, headers)

    @router.get("/applications")
    def applications(request: Request, stage: str = "", source: str = "", page: str = "1"):
        stage = stage if stage in (*STAGES, "open", "closed") else ""
        source = source.strip()
        page_n = _int(page)
        groups = {"open": ("waiting", "interview"), "closed": CLOSED_STAGES}
        rows = ctx.apps.list(stage=stage if stage in STAGES else None, stages=groups.get(stage),
                             source=source or None, limit=PAGE_SIZE, offset=(page_n - 1) * PAGE_SIZE)
        return render(request, "work/applications.html", {
            "tab": "applications", "rows": rows, "stage": stage, "source": source, "sources": ctx.apps.sources(),
            "stages": STAGES, "page": page_n, "has_next": len(rows) == PAGE_SIZE, "today": fx.today(),
            "filtering": bool(stage or source)})

    @router.get("/applications/{app_id}")
    def application(request: Request, app_id: int):
        a = app_or_404(app_id)
        return render(request, "work/application.html", {
            "tab": "applications", "a": a, "events": ctx.apps.events(app_id), "today": fx.today(),
            "work": ctx.works.by_application(app_id), "lead": ctx.leads.get(a.lead_id) if a.lead_id else None,
            "error": "", "kinds": list(Kind)})

    @router.post("/applications/{app_id}/act")
    async def act(request: Request, app_id: int):
        app_or_404(app_id)
        form = await request.form()
        action, text = form.get("action", ""), form.get("text", "")
        today = fx.today()
        target = request.headers.get("hx-target", "")
        try:
            on = parse_day(form.get("on"))
            a = followups.act(ctx, app_id, action, today, on=on, text=text)
        except ValueError as e:
            msg = str(e)
            msg = msg[:1].upper() + msg[1:]
            if target == "followups":
                return render(request, "work/_followups.html", {"due": followups.due(ctx.apps, today), "error": msg, "today": today},
                              400)
            return panel(request, app_id, 400, msg)
        headers = toast(_ACT_TOAST[action].format(days=ctx.settings.followup_days))
        if action == "won":
            headers["HX-Redirect"] = f"/work/jobs/{ctx.works.by_application(a.id).id}"
        if target == "followups":
            return render(request, "work/_followups.html", {"due": followups.due(ctx.apps, today), "today": today},
                          headers=headers)
        return panel(request, app_id, headers=headers)

    @router.post("/applications/{app_id}/note")
    async def note(request: Request, app_id: int):
        app_or_404(app_id)
        text = (await request.form()).get("text", "").strip()
        if text:
            ctx.apps.add_event(app_id, "note", text[:2000])
        return panel(request, app_id, headers=toast("Note added") if text else None)

    @router.post("/applications/{app_id}/edit")
    async def edit(request: Request, app_id: int):
        a = app_or_404(app_id)
        form = await request.form()
        title = form.get("title", "").strip()
        try:
            if not title:
                raise ValueError("Give it a title.")
            fields = {"title": title[:300], "client": form.get("client", "").strip() or None,
                      "source": form.get("source", "").strip() or None, "url": form.get("url", "").strip() or None,
                      "applied_on": parse_day(form.get("applied_on"), a.applied_on)}
            if a.is_open:
                fields["follow_up_on"] = parse_day(form.get("follow_up_on"))
        except ValueError as e:
            return render(request, "work/application.html", {
                "tab": "applications", "a": a, "events": ctx.apps.events(app_id), "today": fx.today(),
                "work": ctx.works.by_application(app_id), "lead": ctx.leads.get(a.lead_id) if a.lead_id else None,
                "error": str(e), "kinds": list(Kind)}, 400)
        ctx.apps.update(app_id, **fields)
        return RedirectResponse(f"/work/applications/{app_id}", status_code=303)

    # Adding by hand

    def add_page(request: Request, what: str, errors: dict | None = None, form=None, status: int = 200):
        what = what if what in ("application", "work", "account") else "application"
        return render(request, "work/add.html", {
            "tab": "", "what": what, "errors": errors or {}, "form": form or {}, "today": fx.today(),
            "followup": fx.today() + timedelta(days=ctx.settings.followup_days), "kinds": list(Kind),
            "currencies": CURRENCIES}, status)

    @router.get("/add")
    def add_form(request: Request, what: str = "application"):
        return add_page(request, what)

    @router.post("/add")
    async def add(request: Request):
        form = await request.form()
        what = form.get("what", "application")
        today = fx.today()
        errors: dict[str, str] = {}

        def field(name, check):
            try:
                return check()
            except ValueError as e:
                errors[name] = str(e)

        if what == "account":
            field("name", lambda: ctx.accounts.create(form.get("name", ""), form.get("currency", "")))
            if errors:
                return add_page(request, what, errors, form, 400)
            return RedirectResponse("/work#accounts", status_code=303)

        title = form.get("title", "").strip()
        if not title:
            errors["title"] = "Give it a title."
        kind = form.get("kind", "") if form.get("kind", "") in {k.value for k in Kind} else None
        if what == "work":
            price = field("price", lambda: parse_amount(form["price"]) if form.get("price", "").strip() else None)
            currency = form.get("currency", "USD") if form.get("currency") in CURRENCIES else "USD"
            started = field("started_on", lambda: parse_day(form.get("started_on"), today))
            if errors:
                return add_page(request, what, errors, form, 400)
            wid = ctx.works.create(title=title[:300], client=form.get("client", "").strip() or None, kind=kind,
                                   price_milli=price, currency=currency, started_on=started)
            return RedirectResponse(f"/work/jobs/{wid}", status_code=303)

        applied = field("applied_on", lambda: parse_day(form.get("applied_on"), today))
        follow = field("follow_up_on", lambda: parse_day(
            form.get("follow_up_on"), (applied or today) + timedelta(days=ctx.settings.followup_days)))
        if errors:
            return add_page(request, "application", errors, form, 400)
        aid = ctx.apps.create(title=title[:300], client=form.get("client", "").strip() or None,
                              source=form.get("source", "").strip() or None, kind=kind,
                              url=form.get("url", "").strip() or None, applied_on=applied, follow_up_on=follow)
        return RedirectResponse(f"/work/applications/{aid}", status_code=303)

    return router


def work_tile(ctx: AppContext) -> dict:
    """The one-line summary the main Overview shows."""
    today = fx.today()
    received = ctx.works.received_between(today.replace(day=1), today)
    return {"month_usd": sum(p.usd_milli or 0 for p in received), "due": len(followups.due(ctx.apps, today))}
