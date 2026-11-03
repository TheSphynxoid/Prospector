import logging
from datetime import datetime

import httpx

from prospector.context import AppContext
from prospector.notify.digest import build_digest, render_email, render_telegram
from prospector.notify.email import send_email_via_bridge
from prospector.notify.telegram import send_telegram

log = logging.getLogger(__name__)


def _describe(e: httpx.HTTPError) -> str:
    """Error text without the request URL (the Telegram URL embeds the bot token)."""
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    return type(e).__name__


def send_digest(ctx: AppContext, now: datetime) -> None:
    """Send the digest on both channels independently; each reports the other's failure."""
    s = ctx.settings
    d = build_digest(ctx.leads, ctx.health, ctx.kv, now, s.dashboard_url)
    tg_ok = email_ok = False
    tg_error = email_error = None

    if s.telegram_token and s.telegram_chat_id:
        try:
            for chunk in render_telegram(d):
                send_telegram(ctx.http, s.telegram_token.get_secret_value(), s.telegram_chat_id, chunk)
            tg_ok = True
        except httpx.HTTPError as e:
            tg_error = _describe(e)
            log.warning("telegram digest failed: %s", tg_error)

    if s.bridge_url:
        subject, text, html = render_email(d)
        if tg_error:
            text = f"⚠ Telegram delivery failed: {tg_error}\n\n{text}"
            html = f"<p>⚠ Telegram delivery failed: {tg_error}</p>\n{html}"
        try:
            send_email_via_bridge(ctx.http, s.bridge_url, s.bridge_secret.get_secret_value().encode(),
                                  subject, text, html)
            email_ok = True
        except httpx.HTTPError as e:
            email_error = _describe(e)
            log.warning("email digest failed: %s", email_error)

    if email_error and tg_ok:
        try:
            send_telegram(ctx.http, s.telegram_token.get_secret_value(), s.telegram_chat_id,
                          f"⚠ Email digest failed: {email_error}")
        except httpx.HTTPError:
            pass

    if tg_ok or email_ok:
        ctx.kv.set("last_digest_at", now.isoformat())
