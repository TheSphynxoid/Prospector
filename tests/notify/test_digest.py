import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from prospector.config import Settings
from prospector.context import AppContext
from prospector.models import Kind, Status
from prospector.notify.digest import build_digest, render_email, render_telegram
from prospector.notify.run import send_digest
from prospector.profile.model import Profile, Targets
from prospector.store.db import connect
from prospector.web.ingest import sign

NOW = datetime(2026, 11, 3, 7, tzinfo=UTC)
URL = "https://prospector.thesphynx.net"
TG = "https://api.telegram.org/botTOKEN/sendMessage"
BRIDGE = "https://bridge.example.workers.dev"


@pytest.fixture
def ctx(tmp_path):
    s = Settings(_env_file=None, llm_api_key="k", bridge_secret="sec", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p", telegram_token="TOKEN", telegram_chat_id="42", bridge_url=BRIDGE)
    prof = Profile(skills={}, projects=[], targets=Targets(kinds=list(Kind), regions=[]))
    return AppContext.create(s, connect(":memory:"), prof, httpx.Client())


def add(ctx, make_lead, n, score=0.5, **kw):
    ids = []
    for i in range(n):
        lid = ctx.leads.insert(make_lead(canonical_url=f"u{len(ids)}-{kw.get('title', '')}-{i}", **kw))
        ctx.scores.save_stage1(lid, score + i / 1000, {})
        ids.append(lid)
    return ids


def digest(ctx):
    return build_digest(ctx.leads, ctx.health, ctx.kv, NOW, URL)


def test_digest_top10_since_last(ctx, make_lead):
    add(ctx, make_lead, 12)
    d = digest(ctx)
    assert len(d.items) == 10
    assert d.items[0].stage1 >= d.items[-1].stage1
    ctx.kv.set("last_digest_at", (NOW + timedelta(hours=1)).isoformat())
    assert digest(ctx).items == []


def test_deadline_section(ctx, make_lead):
    (lid,) = add(ctx, make_lead, 1, deadline=NOW.date() + timedelta(days=2))
    ctx.leads.set_status(lid, Status.STARRED)
    assert [r.lead.id for r in digest(ctx).deadlines] == [lid]


def test_warnings_for_paused_and_drift(ctx):
    ctx.health.record_failure("remotive", "HTTP 503")
    ctx.health.set_paused("remotive", True)
    ctx.health.record_success("hn", 0, drift=True)
    w = digest(ctx).warnings
    assert "remotive paused: HTTP 503" in w and "hn returned suspicious results" in w


def test_telegram_escapes_html(ctx, make_lead):
    add(ctx, make_lead, 1, title="C++ <Senior> & Lead")
    text = "".join(render_telegram(digest(ctx)))
    assert "&lt;Senior&gt; &amp; Lead" in text and "<Senior>" not in text
    assert f"{URL}/lead/" in text


def test_telegram_splits_over_4096(ctx, make_lead):
    add(ctx, make_lead, 10, title="X" * 600)
    d = digest(ctx)
    d.items = d.items * 4
    chunks = render_telegram(d)
    assert len(chunks) > 1 and all(len(c) <= 4096 for c in chunks)
    assert sum(c.count("/lead/") for c in chunks) == 40


def test_render_email(ctx, make_lead):
    add(ctx, make_lead, 3, title="Go <role>")
    subject, text, html = render_email(digest(ctx))
    assert subject == "Prospector: 3 new leads"
    assert "Go <role>" in text and "Go &lt;role&gt;" in html


@respx.mock
def test_send_digest_both_channels(ctx, make_lead):
    add(ctx, make_lead, 2)
    tg = respx.post(TG).mock(return_value=httpx.Response(200, json={"ok": True}))
    br = respx.post(f"{BRIDGE}/digest").mock(return_value=httpx.Response(202))
    send_digest(ctx, NOW)
    assert tg.call_count == 1 and br.call_count == 1
    assert json.loads(tg.calls[0].request.content)["parse_mode"] == "HTML"
    req = br.calls[0].request
    ts = req.headers["X-Prospector-Timestamp"]
    assert req.headers["X-Prospector-Signature"] == "sha256=" + sign(b"sec", ts, req.content)
    assert ctx.kv.get("last_digest_at") == NOW.isoformat()


@respx.mock
def test_email_failure_reported_on_telegram(ctx, make_lead):
    add(ctx, make_lead, 1)
    tg = respx.post(TG).mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.post(f"{BRIDGE}/digest").mock(return_value=httpx.Response(500))
    send_digest(ctx, NOW)
    assert tg.call_count == 2
    assert "Email digest failed" in json.loads(tg.calls[1].request.content)["text"]
    assert ctx.kv.get("last_digest_at") == NOW.isoformat()


@respx.mock
def test_telegram_failure_noted_in_email(ctx, make_lead):
    add(ctx, make_lead, 1)
    respx.post(TG).mock(return_value=httpx.Response(401, json={"ok": False}))
    br = respx.post(f"{BRIDGE}/digest").mock(return_value=httpx.Response(202))
    send_digest(ctx, NOW)
    body = json.loads(br.calls[0].request.content)
    assert body["text"].startswith("⚠ Telegram delivery failed")
    assert "TOKEN" not in body["text"] and "TOKEN" not in body["html"]


@respx.mock
def test_last_digest_not_advanced_when_both_fail(ctx, make_lead):
    add(ctx, make_lead, 1)
    respx.post(TG).mock(return_value=httpx.Response(500))
    respx.post(f"{BRIDGE}/digest").mock(return_value=httpx.Response(500))
    send_digest(ctx, NOW)
    assert ctx.kv.get("last_digest_at") is None
