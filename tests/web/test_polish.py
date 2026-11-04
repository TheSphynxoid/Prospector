import pytest
from fastapi.testclient import TestClient

from prospector import fx
from prospector.models import Kind, Status
from tests.web.conftest import TAILNET


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


def test_leads_count_header(client, ctx, make_lead):
    for i in range(3):
        ctx.leads.insert(make_lead(canonical_url=f"u{i}", kind=Kind.GIG if i == 0 else Kind.JOB))
    assert "Showing 3 of 3" in client.get("/leads").text
    assert "Showing 1 of 1" in client.get("/leads?kind=gig").text


def test_leads_count_paginates(client, ctx, make_lead):
    for i in range(53):
        ctx.leads.insert(make_lead(canonical_url=f"p{i}"))
    assert "Showing 1–50 of 53" in client.get("/leads").text
    assert "Showing 51–53 of 53" in client.get("/leads?page=2").text


def test_count_matches_list_filters(ctx, make_lead):
    ctx.leads.insert(make_lead(canonical_url="a", title="Rust role", kind=Kind.GIG, sources=["hn"]))
    ctx.leads.insert(make_lead(canonical_url="b", title="Go role", kind=Kind.JOB, sources=["remotive"]))
    for kw in ({}, {"kind": Kind.GIG}, {"source": "hn"}, {"q": "Go"}, {"min_score": 0.5}):
        assert ctx.leads.count(Status.NEW, **kw) == len(ctx.leads.list(Status.NEW, limit=500, **kw)), kw


def test_nav_toggle_and_badge(client, ctx):
    page = client.get("/").text
    assert 'class="nav-toggle"' in page and 'aria-controls="mainnav"' in page and 'class="badge"' not in page
    ctx.apps.create(title="Due one", applied_on=fx.today(), follow_up_on=fx.today())
    page = client.get("/leads").text
    work_link = page.split('href="/work"')[1].split("</a>")[0]
    assert '<span class="badge" title="1 follow-up due">1</span>' in work_link


def test_settings_forms_have_dirty_guard(client):
    for area in ("connections", "sources", "ai", "pricing", "schedule", "profile"):
        assert "data-dirty-guard" in client.get(f"/settings/{area}").text, area


def test_detail_has_assistant_jump(client, ctx, make_lead):
    lid = ctx.leads.insert(make_lead())
    page = client.get(f"/lead/{lid}").text
    assert 'href="#assistant"' in page and 'id="assistant"' in page
