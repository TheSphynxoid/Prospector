"""Instant Telegram alerts: a fresh, strong lead the owner can actually get, sent within the hour.

Runs at the end of each scheduler tick. A lead is alerted at most once, and at most `alert_daily_max` a day.
"""
import html
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
    # Telegram parses these as HTML (send_telegram), so lead text is escaped like the digest's.
    lines = [html.escape(lead.title),
             f"{html.escape(lead.company or 'Unknown company')} · "
             f"{html.escape(fmt_pay(lead.pay)) if lead.pay else 'pay not stated'} · {round(score * 100)}%"]
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
    # Freshness is filtered in SQL too, so old strong leads can't crowd a fresh one out of the candidates. The
    # bound is loose (stored offsets vary); the exact 24 h check is below.
    since = (now - WINDOW - timedelta(hours=24)).isoformat()
    rows = ctx.conn.execute(
        "SELECT l.id, s.stage1, l.created_at FROM leads l JOIN scores s ON s.lead_id = l.id "
        "WHERE l.status = 'new' AND s.stage1 >= ? AND COALESCE(l.posted_at, l.created_at) >= ? "
        "ORDER BY s.stage1 DESC LIMIT 500", (s.alert_threshold, since)).fetchall()
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
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                # Telegram refused this one message: mark it so it can't block every alert behind it.
                log.warning("telegram refused an alert for lead %s: %s", lead.id, describe_error(e))
                _mark(ctx, lead.id)
                continue
            log.warning("telegram alert failed: %s", describe_error(e))
            break
        except httpx.HTTPError as e:  # not marked: the next tick retries while the lead is still fresh
            log.warning("telegram alert failed: %s", describe_error(e))
            break
        _mark(ctx, lead.id)
        sent += 1
        ctx.kv.set(day_key, ctx.kv.get(day_key, 0) + 1)
    return sent
