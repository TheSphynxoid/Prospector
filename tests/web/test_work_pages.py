import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from prospector import fx
from tests.web.conftest import TAILNET

T = fx.today()


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


def app_(ctx, **kw):
    return ctx.apps.create(**(dict(title="Go booking API", source="freelancer", applied_on=T - timedelta(days=7),
                                   follow_up_on=T) | kw))


def rates(ctx, tnd=3.0):
    ctx.fx.tnd_override = None
    ctx.conn.execute("INSERT OR REPLACE INTO fx_rates VALUES (?,?,?,?)", (T.isoformat(), "TND", tnd, "t"))


def test_work_overview_empty_state(client):
    r = client.get("/work")
    assert r.status_code == 200 and "Add your first application" in r.text and "None" not in r.text


def test_work_overview_populated(client, ctx):
    rates(ctx)
    acc = ctx.accounts.create("Payoneer", "USD")
    wid = ctx.works.create(title="Scraper bot", price_milli=500_000, currency="USD", started_on=T)
    ctx.works.add_received(wid, 820_000, "USD", T, acc, ctx.fx)
    ctx.works.add_expected(wid, 300_000, "USD", T + timedelta(days=3))
    app_(ctx)
    page = client.get("/work").text
    assert "$820" in page and "≈ 2,460 TND" in page  # received this month
    assert "$300" in page and "1 due this week" in page  # expected
    assert "Go booking API" in page and "Follow-ups due" in page
    assert "Scraper bot" in page and "Payoneer" in page
    assert "Add your first application" not in page


def test_followup_actions_in_place(client, ctx):
    aid = app_(ctx)
    r = client.post(f"/work/applications/{aid}/act", data={"action": "followed_up"},
                    headers={"HX-Request": "true", "HX-Target": "followups"})
    assert r.status_code == 200 and "Go booking API" not in r.text
    assert json.loads(r.headers["HX-Trigger"])["toast"]["msg"] == "Followed up · next reminder in 7 days"
    assert ctx.apps.get(aid).follow_ups == 1


def test_detail_act_rerenders_panel(client, ctx):
    aid = app_(ctx)
    r = client.post(f"/work/applications/{aid}/act", data={"action": "interview", "on": "", "text": "x"},
                    headers={"HX-Request": "true", "HX-Target": "app-panel"})
    assert r.status_code == 400 and "Pick the date" in r.text
    r = client.post(f"/work/applications/{aid}/act",
                    data={"action": "interview", "on": (T + timedelta(days=2)).isoformat(), "text": "Call"},
                    headers={"HX-Request": "true", "HX-Target": "app-panel"})
    assert r.status_code == 200 and 'id="app-panel"' in r.text and "interview: Call" in r.text


def test_won_redirects_to_work(client, ctx):
    aid = app_(ctx)
    r = client.post(f"/work/applications/{aid}/act", data={"action": "won"}, headers={"HX-Request": "true"})
    assert r.headers["HX-Redirect"] == f"/work/jobs/{ctx.works.by_application(aid).id}"


def test_act_unknown_application_404(client):
    assert client.post("/work/applications/999/act", data={"action": "won"}).status_code == 404


@pytest.mark.parametrize("q", ["stage=bogus", "source=", "page=abc", "page=-2", "stage=&source=&page="])
def test_applications_filters_lenient(client, ctx, q):
    app_(ctx)
    r = client.get(f"/work/applications?{q}")
    assert r.status_code == 200 and "Go booking API" in r.text


def test_applications_filter_by_stage(client, ctx):
    app_(ctx, title="Waiting one")
    ctx.apps.update(app_(ctx, title="Lost one"), stage="rejected")
    page = client.get("/work/applications?stage=rejected").text
    assert "Lost one" in page and "Waiting one" not in page


def test_detail_shows_timeline_and_note(client, ctx):
    aid = app_(ctx)
    r = client.post(f"/work/applications/{aid}/note", data={"text": "Sent portfolio <b>"},
                    headers={"HX-Request": "true"})
    assert "Sent portfolio &lt;b&gt;" in r.text
    page = client.get(f"/work/applications/{aid}").text
    assert "Applied" in page and "Sent portfolio" in page
    assert client.get("/work/applications/999").status_code == 404


def test_manual_application(client, ctx):
    r = client.post("/work/add", data={"what": "application", "title": "  ", "applied_on": ""})
    assert r.status_code == 400 and "Give it a title" in r.text and ctx.apps.list() == []
    r = client.post("/work/add", data={"what": "application", "title": "Referral site", "client": "Cousin",
                                       "applied_on": "", "follow_up_on": ""}, follow_redirects=False)
    a = ctx.apps.list()[0]
    assert r.status_code == 303 and r.headers["location"] == f"/work/applications/{a.id}"
    assert a.applied_on == T and a.follow_up_on == T + timedelta(days=7)


def test_manual_work_and_account(client, ctx):
    r = client.post("/work/add", data={"what": "work", "title": "Logo", "price": "1 200,50", "currency": "TND",
                                       "started_on": ""}, follow_redirects=False)
    w = ctx.works.list()[0]
    assert r.status_code == 303 and (w.price_milli, w.currency, w.started_on) == (1_200_500, "TND", T)
    r = client.post("/work/add", data={"what": "work", "title": "x", "price": "abc", "currency": "USD"})
    assert r.status_code == 400 and "amount" in r.text
    r = client.post("/work/add", data={"what": "account", "name": "BIAT", "currency": "TND"}, follow_redirects=False)
    assert r.status_code == 303 and ctx.accounts.list()[0].name == "BIAT"
    assert client.post("/work/add", data={"what": "account", "name": "BIAT", "currency": "TND"}).status_code == 400
    assert client.get("/work/add?what=bogus").status_code == 200


def test_nav_has_work(client):
    page = client.get("/").text
    i, j, k = page.index('href="/leads"'), page.index('href="/work"'), page.index('href="/health"')
    assert i < j < k


def test_main_overview_work_tile(client, ctx):
    app_(ctx)
    page = client.get("/").text
    assert "1 follow-up due" in page and 'href="/work"' in page
