from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from prospector.assist.fetch import FetchResult
from tests.assist.conftest import FakeLLM
from tests.web.conftest import TAILNET

GOOD = {"proposal": "I built a hotel room-mapping engine in Go. " * 4, "estimate_hours": 10, "rationale": "Small."}


@pytest.fixture
def fake(ctx):
    ctx.assistant_llm = FakeLLM()
    return ctx.assistant_llm


@pytest.fixture
def fetched(monkeypatch):
    calls = []

    def fake_fetch(lead, *a, **k):
        calls.append(lead.id)
        return FetchResult(None, None, "The page needs a login or blocked the request — paste the posting instead.")
    monkeypatch.setattr("prospector.assist.fetch.fetch_posting", fake_fetch)
    return calls


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


@pytest.fixture
def lid(ctx, make_lead):
    return ctx.leads.insert(make_lead())


def test_detail_shows_assistant_and_triggers_fetch(ctx, client, lid, fetched):
    page = client.get(f"/lead/{lid}").text
    assert 'id="assistant"' in page
    assert fetched == [lid] and ctx.assist.get(lid).fetch_tried
    client.get(f"/lead/{lid}")
    assert fetched == [lid]  # tried once


def test_posting_status_shows_note_and_paste_box(client, lid, fetched):
    client.get(f"/lead/{lid}")
    r = client.get(f"/lead/{lid}/assist/posting-status")
    assert "needs a login" in r.text and "<details" in r.text and " open" in r.text


def test_message_round_trip(client, lid, fake, fetched):
    fake.replies = ["Looks legit."]
    r = client.post(f"/lead/{lid}/assist/message", data={"text": "is it legit?"})
    assert r.status_code == 200 and "is it legit?" in r.text and "Looks legit." in r.text


def test_empty_message_ignored(client, lid, fake, fetched):
    r = client.post(f"/lead/{lid}/assist/message", data={"text": "   "})
    assert r.status_code == 200 and fake.calls == []


def test_reply_html_escaped(client, lid, fake, fetched):
    fake.replies = ['<script>alert(1)</script><a href="javascript:x">y</a>']
    r = client.post(f"/lead/{lid}/assist/message", data={"text": "hi"})
    assert "&lt;script&gt;" in r.text and "<script>alert" not in r.text and 'href="javascript' not in r.text


def test_buttons_disable_in_flight(client, lid, fetched):
    page = client.get(f"/lead/{lid}").text
    assert page.count("hx-disabled-elt") >= 2


def test_bid_fragment(ctx, client, lid, fake, fetched):
    fake.replies = [GOOD]
    r = client.post(f"/lead/{lid}/assist/bid")
    assert "<textarea" in r.text and "room-mapping" in r.text
    assert "$250" in r.text and "≈ 750 TND" in r.text and "$150" in r.text and "2 days" in r.text
    assert "Bid drafted" in r.text  # out-of-band chat summary
    assert f"/lead/{lid}" in client.get(f"/lead/{lid}").text and "$250" in client.get(f"/lead/{lid}").text


def test_bid_error_shown(client, lid, fake, fetched):
    fake.replies = ["nope", "nope"]
    r = client.post(f"/lead/{lid}/assist/bid")
    assert "usable bid" in r.text


def test_paste_posting_saved_and_capped(ctx, client, lid, fetched):
    r = client.post(f"/lead/{lid}/assist/posting", data={"posting": "p" * 25000})
    row = ctx.assist.get(lid)
    assert r.status_code == 200 and len(row.posting) == 20000 and row.posting_origin == "pasted"
    assert "pasted" in r.text


def test_fetch_again(ctx, client, lid, fetched):
    client.post(f"/lead/{lid}/assist/fetch")
    assert fetched == [lid]


def test_clear_chat(ctx, client, lid, fake, fetched):
    client.post(f"/lead/{lid}/assist/message", data={"text": "hi"})
    client.post(f"/lead/{lid}/assist/clear")
    assert ctx.assist.messages(lid) == []


def test_cross_site_refused(client, lid, fetched):
    r = client.post(f"/lead/{lid}/assist/message", data={"text": "hi"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


@pytest.mark.parametrize("path", ["message", "bid", "posting", "fetch", "clear"])
def test_unknown_lead_404(client, path):
    assert client.post(f"/lead/999/assist/{path}", data={"text": "x", "posting": "x"}).status_code == 404


def test_overview_shows_assistant_usage(ctx, client):
    ctx.kv.set(f"assistant_calls:{datetime.now(UTC).date().isoformat()}", 3)
    page = client.get("/").text
    assert "Assistant today" in page and "3<small>/100</small>" in page
