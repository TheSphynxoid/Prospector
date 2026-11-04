from urllib.parse import parse_qs, urlparse

import json

import pytest
from fastapi.testclient import TestClient

from prospector.models import Status
from prospector.store.feedback import REASONS
from tests.web.conftest import TAILNET


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


def test_reasons_order():
    assert list(REASONS) == ["too_senior", "no_region", "wrong_stack", "not_interested", "other"]
    assert REASONS["no_region"] == "Can't apply from here"


def test_dismiss_reason_stored(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    r = client.post(f"/lead/{lid}/dismiss", data={"reason": "too_senior"})
    assert r.status_code == 200 and ctx.leads.get(lid).status is Status.DISMISSED
    assert ctx.feedback.negative_ids() == [] and ctx.feedback.misses() == [(lid, "too_senior")]


def test_wrong_stack_is_negative(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    client.post(f"/lead/{lid}/dismiss", data={"reason": "wrong_stack"})
    assert ctx.feedback.negative_ids() == [lid] and ctx.feedback.misses() == []


def test_plain_and_unknown_reason_dismiss_are_negative(ctx, client, make_lead):
    a = ctx.leads.insert(make_lead(canonical_url="a"))
    b = ctx.leads.insert(make_lead(canonical_url="b"))
    client.post(f"/lead/{a}/dismiss")
    client.post(f"/lead/{b}/dismiss", data={"reason": "bogus"})
    assert ctx.feedback.negative_ids() == [a, b]


def test_reason_ignored_for_other_actions(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    client.post(f"/lead/{lid}/star", data={"reason": "too_senior"})
    assert ctx.conn.execute("SELECT COUNT(*) FROM dismiss_reasons").fetchone()[0] == 0


def test_undo_dismiss_reason(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    r = client.post(f"/lead/{lid}/dismiss", data={"reason": "no_region"})
    undo = json.loads(r.headers["HX-Trigger"])["toast"]["undo"]
    q = parse_qs(urlparse(undo).query)
    client.post(f"/lead/{lid}/undo", params={"to": q["to"][0], "fb": q["fb"][0]})
    assert ctx.conn.execute("SELECT COUNT(*) FROM dismiss_reasons").fetchone()[0] == 0
    assert ctx.feedback.misses() == [] and ctx.leads.get(lid).status is Status.NEW


def test_misses_card(ctx, client, make_lead):
    ctx.profile.targets.levels = ["intern", "junior"]
    missed = ctx.leads.insert(make_lead(canonical_url="m", title="Backend Engineer", remote_region="Tokyo"))
    caught = ctx.leads.insert(make_lead(canonical_url="c", title="Senior Backend Engineer"))
    for lid in (missed, caught):
        client.post(f"/lead/{lid}/dismiss", data={"reason": "too_senior"})
    page = client.get("/settings/sources").text
    assert "Detection misses" in page
    section = page.split("Detection misses", 1)[1]
    assert "Backend Engineer" in section and "Tokyo" in section and "Senior Backend Engineer" not in section


def test_misses_card_empty(ctx, client):
    assert "No misses yet." in client.get("/settings/sources").text


def test_dismiss_menu_rendered(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    page = client.get("/?tab=new").text
    assert "data-dismiss-menu" in page
    for label in REASONS.values():
        assert label.replace("'", "&#39;") in page
    assert "data-dismiss-menu" in client.get(f"/lead/{lid}").text
