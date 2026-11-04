"""Instant Telegram alerts: a fresh, strong lead the owner can actually get, sent within the hour.

Runs at the end of each scheduler tick. A lead is alerted at most once, and at most `alert_daily_max` a day.
"""
import logging
from datetime import UTC, datetime, timedelta

import httpx

from prospector import fx
from prospector.context import AppContext
from prospector.http import describe_error
from prospector.notify.telegram import send_telegram
from prospector.rank.reach import reach
from prospector.web.format import fmt_pay

log = logging.getLogger(__name__)
WINDOW = timedelta(hours=24)
KEEP = 500  # alerted lead ids remembered


def _ts(value) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _mark(ctx: AppContext, lead_id: int) -> None:
    ctx.kv.set("alerted", [*ctx.kv.get("alerted", []), lead_id][-KEEP:])


def _message(ctx: AppContext, lead, score: float) -> str:
    bids = ctx.signals.bids(lead.id)
    base = (ctx.settings.dashboard_url or "").rstrip("/")
    lines = [lead.title,
             f"{lead.company or 'Unknown company'} · {fmt_pay(lead.pay) if lead.pay else 'pay not stated'} · "
             f"{round(score * 100)}%"]
    if bids is not None:
        lines.append(f"{bids} bid{'s' if bids != 1 else ''}")
    lines.append(f"{base}/lead/{lead.id}")
    return "\n".join(lines)


def send_alerts(ctx: AppContext, now: datetime) -> int:
    s = ctx.settings
    if not (s.alerts_enabled and s.telegram_token and s.telegram_chat_id):
        return 0
    day_key = f"alerts:{fx.today(now).isoformat()}"
    left = s.alert_daily_max - ctx.kv.get(day_key, 0)
    if left <= 0:
        return 0
    done = set(ctx.kv.get("alerted", []))
    rows = ctx.conn.execute(
        "SELECT l.id, s.stage1, l.created_at FROM leads l JOIN scores s ON s.lead_id = l.id "
        "WHERE l.status = 'new' AND s.stage1 >= ? ORDER BY s.stage1 DESC LIMIT 50", (s.alert_threshold,)).fetchall()
    sent = 0
    for row in rows:
        if sent >= left:
            break
        if row["id"] in done:
            continue
        lead = ctx.leads.get(row["id"])
        when = _ts(lead.posted_at) or _ts(row["created_at"])
        if when is None or now - when > WINDOW or reach(lead, ctx.profile)[1] is not None:
            continue
        try:
            send_telegram(ctx.http, s.telegram_token.get_secret_value(), s.telegram_chat_id,
                          _message(ctx, lead, row["stage1"]))
        except httpx.HTTPError as e:  # not marked: the next tick retries while the lead is still fresh
            log.warning("telegram alert failed: %s", describe_error(e))
            break
        _mark(ctx, lead.id)
        sent += 1
        ctx.kv.set(day_key, ctx.kv.get(day_key, 0) + 1)
    return sent
