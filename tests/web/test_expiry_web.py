import pytest
from fastapi.testclient import TestClient

from prospector.models import Status
from tests.web.conftest import TAILNET


@pytest.fixture
def client(ctx, app, monkeypatch):
    monkeypatch.setattr("prospector.assist.fetch.fetch_posting",
                        lambda lead, *a, **k: __import__("prospector.assist.fetch", fromlist=["FetchResult"]).FetchResult(None, None, "n/a"))
    return TestClient(app, client=TAILNET)


def expired(ctx, make_lead, url="https://e/1"):
    lid = ctx.leads.insert(make_lead(canonical_url=url, title="Old gig"))
    ctx.leads.set_status(lid, Status.EXPIRED)
    ctx.expiry.flag(lid, "age", "Posted 30 days ago.")
    return lid


def test_expired_tab_lists_with_reason(ctx, client, make_lead):
    expired(ctx, make_lead)
    page = client.get("/leads?tab=expired").text
    assert "Old gig" in page and "Expired: Posted 30 days ago." in page
    assert 'href="/leads?tab=expired"' in client.get("/leads").text
    assert "Old gig" not in client.get("/leads").text


def test_reset_keeps_it_open(ctx, client, make_lead):
    lid = expired(ctx, make_lead)
    client.post(f"/lead/{lid}/reset")
    assert ctx.leads.get(lid).status is Status.NEW
    assert ctx.leads.get_row(lid).closed_reason is None and "age" in ctx.expiry.ignored(lid)


def test_starred_badge_and_still_open(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead(title="Starred one"))
    ctx.leads.set_status(lid, Status.STARRED)
    ctx.expiry.flag(lid, "freelancer", "Closed on Freelancer.")
    page = client.get("/leads?tab=starred").text
    assert "May have closed: Closed on Freelancer." in page and f"/lead/{lid}/still-open" in page
    r = client.post(f"/lead/{lid}/still-open")
    assert r.status_code == 200 and "May have closed" not in r.text
    assert ctx.leads.get(lid).status is Status.STARRED and "freelancer" in ctx.expiry.ignored(lid)


def test_detail_and_assistant_warn(ctx, client, make_lead):
    lid = expired(ctx, make_lead)
    page = client.get(f"/lead/{lid}").text
    assert page.count("Posted 30 days ago.") >= 2  # status badge and the assistant warning
    assert "may already be closed" in page


def test_still_open_on_detail_page(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    ctx.leads.set_status(lid, Status.APPLIED)
    ctx.expiry.flag(lid, "gone", "The posting page is gone (404).")
    r = client.post(f"/lead/{lid}/still-open", headers={"HX-Target": "detail-actions"})
    assert 'id="detail-actions"' in r.text and "gone" not in r.text
