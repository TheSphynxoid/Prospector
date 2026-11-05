from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from prospector.notify import alerts
from prospector.notify.alerts import send_alerts
from tests.test_scheduler import make_ctx

NOW = datetime(2026, 11, 5, 10, tzinfo=UTC)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    c = make_ctx(tmp_path)
    c.settings.telegram_token = SecretStr("tok")
    c.settings.telegram_chat_id = "42"
    c.settings.dashboard_url = "https://p.test"
    c.profile.targets.levels = ["intern", "junior"]
    c.sent = []
    monkeypatch.setattr(alerts, "send_telegram", lambda http, token, chat, text: c.sent.append(text))
    return c


def add(ctx, make_lead, i, score, title="Go dev", posted=NOW, **kw):
    lid = ctx.leads.insert(make_lead(canonical_url=f"https://x.test/{i}", title=title, posted_at=posted, **kw))
    ctx.scores.save_stage1(lid, score, {"final": score})
    return lid


def test_alerts_sends_fresh_reachable_best_first(ctx, make_lead):
    add(ctx, make_lead, 1, 0.7, title="Go dev seventy")
    best = add(ctx, make_lead, 2, 0.9, title="Go dev ninety", company="Acme")
    add(ctx, make_lead, 3, 0.5, title="Go dev fifty")
    assert send_alerts(ctx, NOW) == 2
    assert "Go dev ninety" in ctx.sent[0] and "Go dev seventy" in ctx.sent[1]
    assert f"https://p.test/lead/{best}" in ctx.sent[0] and "90%" in ctx.sent[0] and "Acme" in ctx.sent[0]
    assert "pay not stated" in ctx.sent[0]


def test_alert_shows_bids(ctx, make_lead):
    lid = add(ctx, make_lead, 1, 0.9)
    ctx.signals.set_bids(lid, 7)
    send_alerts(ctx, NOW)
    assert "7 bids" in ctx.sent[0]


def test_alerts_skip_tagged(ctx, make_lead):
    add(ctx, make_lead, 1, 0.95, title="Senior Go dev")
    add(ctx, make_lead, 2, 0.95, title="Go dev", remote_region="US only")
    assert send_alerts(ctx, NOW) == 0


def test_alerts_window(ctx, make_lead):
    add(ctx, make_lead, 1, 0.9, posted=NOW - timedelta(hours=30))
    assert send_alerts(ctx, NOW) == 0
    lid = add(ctx, make_lead, 2, 0.9, posted=None)  # no posting date: first seen counts
    ctx.conn.execute("UPDATE leads SET created_at = ? WHERE id = ?", ((NOW - timedelta(hours=2)).isoformat(), lid))
    assert send_alerts(ctx, NOW) == 1
    assert send_alerts(ctx, NOW + timedelta(days=2)) == 0


def test_alerts_daily_max(ctx, make_lead):
    for i in range(8):
        add(ctx, make_lead, i, 0.9 - i / 100, posted=NOW)
    assert send_alerts(ctx, NOW) == 6
    assert send_alerts(ctx, NOW + timedelta(hours=1)) == 0
    assert send_alerts(ctx, NOW + timedelta(hours=14)) == 2  # the next Tunis day, still within 24 h


def test_alert_not_repeated_after_rescore(ctx, make_lead):
    lid = add(ctx, make_lead, 1, 0.9)
    send_alerts(ctx, NOW)
    ctx.scores.save_stage1(lid, 0.92, {"final": 0.92})
    send_alerts(ctx, NOW + timedelta(minutes=30))
    assert len(ctx.sent) == 1


def test_alerts_retry_after_error(ctx, make_lead, monkeypatch):
    add(ctx, make_lead, 1, 0.9)

    def boom(*a):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(alerts, "send_telegram", boom)
    assert send_alerts(ctx, NOW) == 0
    monkeypatch.setattr(alerts, "send_telegram", lambda http, token, chat, text: ctx.sent.append(text))
    assert send_alerts(ctx, NOW) == 1


def test_alerts_disabled_or_unconfigured(ctx, make_lead):
    add(ctx, make_lead, 1, 0.9)
    ctx.settings.alerts_enabled = False
    assert send_alerts(ctx, NOW) == 0
    ctx.settings.alerts_enabled = True
    ctx.settings.telegram_chat_id = None
    assert send_alerts(ctx, NOW) == 0
    assert ctx.sent == []


def test_alerts_only_new_status(ctx, make_lead):
    from prospector.models import Status
    lid = add(ctx, make_lead, 1, 0.9)
    ctx.leads.set_status(lid, Status.DISMISSED)
    assert send_alerts(ctx, NOW) == 0


def test_alerted_list_capped(ctx):
    ctx.kv.set("alerted", list(range(600)))
    alerts._mark(ctx, 999)
    kept = ctx.kv.get("alerted")
    assert len(kept) == 500 and kept[-1] == 999


def test_alert_escapes_html(ctx, make_lead):
    add(ctx, make_lead, 1, 0.9, title="Go/C++ dev <remote> & more", company="A<B>")
    send_alerts(ctx, NOW)
    assert "&lt;remote&gt; &amp; more" in ctx.sent[0] and "A&lt;B&gt;" in ctx.sent[0]


def test_alert_rejected_message_does_not_block_queue(ctx, make_lead, monkeypatch):
    bad = add(ctx, make_lead, 1, 0.95, title="bad one")
    add(ctx, make_lead, 2, 0.9, title="good one")

    def send(http, token, chat, text):
        if "bad one" in text:
            raise httpx.HTTPStatusError("400", request=httpx.Request("POST", "https://t.test"),
                                        response=httpx.Response(400))
        ctx.sent.append(text)
    monkeypatch.setattr(alerts, "send_telegram", send)
    assert send_alerts(ctx, NOW) == 1 and "good one" in ctx.sent[0]
    assert bad in ctx.kv.get("alerted")  # a message Telegram refuses is not retried forever


def test_alerts_not_starved_by_old_top_leads(ctx, make_lead):
    for i in range(60):
        add(ctx, make_lead, i, 0.95, title=f"old {i}", posted=NOW - timedelta(days=5))
    add(ctx, make_lead, 99, 0.62, title="fresh one")
    assert send_alerts(ctx, NOW) == 1 and "fresh one" in ctx.sent[0]
