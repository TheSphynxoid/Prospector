from datetime import UTC, datetime, time

import pytest
from fastapi.testclient import TestClient

from prospector.models import Kind, Status
from prospector.web.dashboard import next_digest
from tests.web.conftest import TAILNET


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


def test_overview_renders_on_empty_database(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "New today" in r.text and "No new leads yet" in r.text


def test_overview_shows_top_matches_and_counts(ctx, client, make_lead):
    for i, score in enumerate([0.3, 0.9, 0.6]):
        lid = ctx.leads.insert(make_lead(canonical_url=f"u{i}", title=f"Role {score}", kind=Kind.BOUNTY,
                                         sources=["hn"]))
        ctx.scores.save_stage1(lid, score, {})
    ctx.scores.save_stage2(lid, {"verdict": "maybe", "fit_summary": "Decent.", "lead_with_project": "P",
                                 "red_flags": [], "pay_estimate": None})
    ctx.leads.set_status(lid, Status.STARRED)
    page = client.get("/").text
    assert page.index("Role 0.9") < page.index("Role 0.3")
    assert "Role 0.6" not in page.split('id="top"')[1].split("</section>")[0]  # starred, so not a new match
    assert "hn" in page and "bounty" in page


def test_overview_escapes_titles(ctx, client, make_lead):
    ctx.leads.insert(make_lead(title="<img src=x onerror=alert(1)>"))
    assert "<img src=x" not in client.get("/").text


def test_old_list_links_redirect_to_leads(client):
    r = client.get("/?tab=starred&kind=job", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/leads?tab=starred&kind=job"


def test_leads_page_keeps_filters_when_paging(ctx, client, make_lead):
    for i in range(51):
        ctx.leads.insert(make_lead(canonical_url=f"p{i}", kind=Kind.CONTRACT))
    page = client.get("/leads?kind=contract").text
    assert "page=2" in page and "kind=contract" in page.split("page=2")[0].rsplit('href="', 1)[1]


def test_nav_marks_current_page(client):
    assert 'aria-current="page" href="/leads"' in client.get("/leads").text
    assert 'aria-current="page" href="/"' in client.get("/").text


@pytest.mark.parametrize("now, at, expected", [
    (datetime(2026, 11, 3, 6, 59, tzinfo=UTC), time(8, 0), datetime(2026, 11, 3, 7, tzinfo=UTC)),  # 07:59 Tunis
    (datetime(2026, 11, 3, 7, 0, tzinfo=UTC), time(8, 0), datetime(2026, 11, 4, 7, tzinfo=UTC)),
    (datetime(2026, 11, 3, 7, 0, tzinfo=UTC), time(19, 30), datetime(2026, 11, 3, 18, 30, tzinfo=UTC)),
])
def test_next_digest_at_configured_tunis_time(now, at, expected):
    assert next_digest(now, at) == expected
