import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from prospector import fx
from prospector.models import Pay
from tests.web.conftest import TAILNET


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


@pytest.fixture
def lead(ctx, make_lead):
    return ctx.leads.insert(make_lead(title="Go booking API", company="Voyages", sources=["freelancer", "hn"],
                                      pay=Pay(500, 500, "USD", "fixed")))


def toast(r):
    return json.loads(r.headers["HX-Trigger"])["toast"]


def test_applied_creates_application(client, ctx, lead):
    r = client.post(f"/lead/{lead}/applied")
    a = ctx.apps.by_lead(lead)
    assert (a.stage, a.title, a.client, a.source, a.kind, a.from_lead_action) == \
        ("waiting", "Go booking API", "Voyages", "freelancer", "job", True)
    assert a.applied_on == fx.today() and a.follow_up_on == fx.today() + timedelta(days=7)
    assert toast(r)["msg"] == "Marked applied · tracking in Work"


def test_applied_twice_one_application(client, ctx, lead):
    client.post(f"/lead/{lead}/applied")
    client.post(f"/lead/{lead}/applied")
    assert len(ctx.apps.list()) == 1


def test_undo_removes_untouched_application(client, ctx, lead):
    undo = toast(client.post(f"/lead/{lead}/applied"))["undo"]
    client.post(undo)
    assert ctx.apps.by_lead(lead) is None


def test_undo_keeps_application_with_events(client, ctx, lead):
    undo = toast(client.post(f"/lead/{lead}/applied"))["undo"]
    ctx.apps.add_event(ctx.apps.by_lead(lead).id, "note", "sent portfolio")
    client.post(undo)
    assert ctx.apps.by_lead(lead) is not None


def test_undo_keeps_manually_linked_application(client, ctx, lead):
    ctx.apps.create(lead_id=lead, title="t", applied_on=fx.today())
    undo = toast(client.post(f"/lead/{lead}/applied"))["undo"]
    client.post(undo)
    assert ctx.apps.by_lead(lead) is not None


def test_detail_shows_application_line(client, ctx, lead):
    assert "Application:" not in client.get(f"/lead/{lead}").text
    client.post(f"/lead/{lead}/applied")
    aid = ctx.apps.by_lead(lead).id
    page = client.get(f"/lead/{lead}").text
    assert "Application: waiting" in page and f'href="/work/applications/{aid}"' in page
    frag = client.post(f"/lead/{lead}/star", headers={"HX-Target": "detail-actions"}).text
    assert f'href="/work/applications/{aid}"' in frag
