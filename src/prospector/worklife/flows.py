"""Where the Work area meets leads: applying to a lead starts tracking it."""
import sqlite3
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prospector.context import AppContext


def on_applied(ctx: "AppContext", lead_id: int, today: date) -> int:
    """The application for this lead, created on the first *Applied* (pressing it again changes nothing)."""
    existing = ctx.apps.by_lead(lead_id)
    if existing:
        return existing.id
    lead = ctx.leads.get(lead_id)
    try:
        return ctx.apps.create(
            lead_id=lead_id, title=lead.title, client=lead.company, source=(lead.sources or [None])[0],
            kind=lead.kind.value, url=lead.canonical_url, applied_on=today,
            follow_up_on=today + timedelta(days=ctx.settings.followup_days), from_lead_action=True)
    except sqlite3.IntegrityError:  # two clicks racing: the other one created it
        return ctx.apps.by_lead(lead_id).id


def on_unapplied(ctx: "AppContext", lead_id: int) -> bool:
    """Undo of *Applied*: drop the application only if that click created it and nothing happened since."""
    a = ctx.apps.by_lead(lead_id)
    if a is None or not a.from_lead_action or a.stage != "waiting":
        return False
    if [e.kind for e in ctx.apps.events(a.id)] != ["applied"]:
        return False
    ctx.apps.delete(a.id)
    return True


def _price(pay) -> tuple[int | None, str]:
    """A single fixed amount from the posting, in its currency; anything vaguer stays unset (USD)."""
    from prospector.fx import CURRENCIES
    from prospector.money import to_milli

    if pay is None or pay.period != "fixed" or pay.currency not in CURRENCIES:
        return None, "USD"
    bounds = {b for b in (pay.min, pay.max) if b is not None}
    return (to_milli(bounds.pop()), pay.currency) if len(bounds) == 1 else (None, "USD")


def on_won(ctx: "AppContext", app_id: int, today: date) -> int:
    """The work item for a won application, created once."""
    existing = ctx.works.by_application(app_id)
    if existing:
        return existing.id
    a = ctx.apps.get(app_id)
    lead = ctx.leads.get(a.lead_id) if a.lead_id else None
    price, currency = _price(lead.pay if lead else None)
    try:
        return ctx.works.create(application_id=app_id, lead_id=a.lead_id, title=a.title, client=a.client,
                                kind=a.kind, price_milli=price, currency=currency, started_on=today)
    except sqlite3.IntegrityError:  # created by a concurrent click
        return ctx.works.by_application(app_id).id
