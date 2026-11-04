"""When an application needs a nudge, what each answer does, and closing the ones that went quiet."""
from datetime import date, timedelta
from typing import TYPE_CHECKING

from prospector.store.applications import CLOSED_STAGES, OPEN_STAGES, Application, ApplicationRepo

if TYPE_CHECKING:
    from prospector.context import AppContext

ACTIONS = ("followed_up", "interview", "snooze", "won", *CLOSED_STAGES)
_LABEL = {"won": "won", "rejected": "rejected", "no_reply": "no reply", "withdrawn": "withdrawn"}


def due(apps: ApplicationRepo, today: date) -> list[Application]:
    """Open applications whose follow-up date has come, oldest first."""
    rows = apps.conn.execute(
        f"SELECT id FROM applications WHERE stage IN ({', '.join('?' * len(OPEN_STAGES))}) "
        "AND follow_up_on IS NOT NULL AND follow_up_on <= ? ORDER BY follow_up_on, id",
        (*OPEN_STAGES, today.isoformat()))
    return [apps.get(r["id"]) for r in rows]


def act(ctx: "AppContext", app_id: int, action: str, today: date, *, on: date | None = None,
        text: str = "") -> Application:
    apps = ctx.apps
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if apps.get(app_id) is None:
        raise LookupError(app_id)
    period = timedelta(days=ctx.settings.followup_days)
    if action == "followed_up":
        a = apps.get(app_id)
        apps.update(app_id, follow_ups=a.follow_ups + 1, follow_up_on=today + period)
        apps.add_event(app_id, "followed_up", text)
    elif action == "interview":
        if on is None:
            raise ValueError("pick the date of the next step")
        apps.update(app_id, stage="interview", follow_up_on=on, next_step=text.strip() or None)
        apps.add_event(app_id, "stage", f"interview: {text.strip()}" if text.strip() else "interview")
    elif action == "snooze":
        if on is None:
            raise ValueError("pick a date")
        apps.update(app_id, follow_up_on=on)
        apps.add_event(app_id, "snoozed", on.isoformat())
    else:
        apps.update(app_id, stage=action, closed_on=today, follow_up_on=None)
        apps.add_event(app_id, "stage", _LABEL[action] + (f": {text.strip()}" if text.strip() else ""))
    return apps.get(app_id)


def auto_close(ctx: "AppContext", today: date) -> int:
    """Waiting applications followed up at least once, then quiet for another full period: closed as no reply."""
    limit = today - timedelta(days=ctx.settings.followup_days)
    rows = ctx.conn.execute(
        "SELECT id FROM applications WHERE stage = 'waiting' AND follow_ups >= 1 "
        "AND follow_up_on IS NOT NULL AND follow_up_on < ?", (limit.isoformat(),)).fetchall()
    for r in rows:
        ctx.apps.update(r["id"], stage="no_reply", closed_on=today, follow_up_on=None)
        ctx.apps.add_event(r["id"], "stage", "closed: no answer")
    return len(rows)
