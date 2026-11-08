"""The read-only JSON API for agents: /api/leads, /api/leads/{id}, /api/sources."""
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from prospector.models import Kind, Remote, Status
from tests.web.conftest import OUTSIDE, TAILNET


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


@pytest.fixture
def ids(ctx, make_lead):
    a = ctx.leads.insert(make_lead(canonical_url="https://pfebooks.com/stages/a", title="Go backend PFE",
                                   company="Acme", kind=Kind.PFE, remote=Remote.NO, locations=["Tunis, Tunisie"],
                                   body="Missions\n\nPostuler : jobs@acme.tn", sources=["pfebooks"],
                                   posted_at=datetime(2026, 11, 5, tzinfo=UTC)))
    b = ctx.leads.insert(make_lead(canonical_url="https://e/b", title="Remote Go gig", kind=Kind.GIG,
                                   sources=["freelancer"], posted_at=datetime(2026, 10, 1, tzinfo=UTC)))
    ctx.scores.save_stage1(a, 0.71, {"skills": 0.8})
    ctx.scores.save_stage2(a, {"verdict": "strong", "fit_summary": "Go and gRPC", "red_flags": ["unpaid?"]})
    ctx.scores.save_stage1(b, 0.4, {})
    return a, b


def test_lists_ranked_with_scores_and_review(client, ids):
    r = client.get("/api/leads")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2 and data["offset"] == 0 and data["limit"] == 50
    first = data["leads"][0]
    assert first["id"] == ids[0] and first["score"] == 0.71 and first["verdict"] == "strong"
    assert first["fit_summary"] == "Go and gRPC" and first["kind"] == "pfe" and first["sources"] == ["pfebooks"]
    assert first["locations"] == ["Tunis, Tunisie"] and first["emails"] == ["jobs@acme.tn"]
    assert first["url"] == "https://pfebooks.com/stages/a" and first["api_url"] == f"/api/leads/{ids[0]}"
    assert "body" not in first  # the list stays light; the detail has the posting


def test_filters_combine(client, ids):
    def titles(query):
        return [x["title"] for x in client.get(f"/api/leads?{query}").json()["leads"]]
    assert titles("source=pfebooks") == ["Go backend PFE"]
    assert titles("not_source=pfebooks") == ["Remote Go gig"]
    assert titles("kind=pfe&kind=internship") == ["Go backend PFE"]
    assert titles("location=tunis&has_email=true") == ["Go backend PFE"]
    assert titles("q=postuler") == ["Go backend PFE"]  # searches the posting too
    assert titles("verdict=strong") == ["Go backend PFE"]
    assert titles("min_score=0.5") == ["Go backend PFE"]
    assert titles("since=2026-11-01") == ["Go backend PFE"]
    assert titles("sort=date&limit=1&offset=1") == ["Go backend PFE"]


def test_since_in_days(client, ids, monkeypatch):
    import prospector.web.api as api
    monkeypatch.setattr(api, "_now", lambda: datetime(2026, 11, 8, tzinfo=UTC))
    assert [x["title"] for x in client.get("/api/leads?since=7d").json()["leads"]] == ["Go backend PFE"]


def test_status_tab(client, ctx, ids):
    ctx.leads.set_status(ids[1], Status.STARRED)
    assert [x["id"] for x in client.get("/api/leads?status=starred").json()["leads"]] == [ids[1]]


@pytest.mark.parametrize("query", ["kind=nope", "status=bogus", "verdict=great", "min_score=2", "limit=0",
                                   "limit=500", "offset=-1", "since=yesterday", "sort=weird", "source=nosuch"])
def test_bad_values_are_errors_not_silent(client, ids, query):
    r = client.get(f"/api/leads?{query}")
    assert r.status_code == 422


def test_unknown_source_names_the_known_ones(client, ids):
    detail = client.get("/api/leads?source=nosuch").json()["detail"]
    assert "nosuch" in detail and "freelancer" in detail


def test_detail_has_posting_breakdown_review_and_application(client, ctx, ids):
    from prospector.worklife.flows import on_applied
    ctx.leads.set_status(ids[0], Status.APPLIED)
    on_applied(ctx, ids[0], date(2026, 11, 7))
    r = client.get(f"/api/leads/{ids[0]}")
    assert r.status_code == 200
    d = r.json()
    assert d["body"].startswith("Missions") and d["posting_origin"] == "source"
    assert d["breakdown"] == {"skills": 0.8} and d["review"]["red_flags"] == ["unpaid?"]
    assert d["status"] == "applied" and d["application"]["stage"] == "waiting"
    assert d["application"]["applied_on"] == "2026-11-07"
    assert d["dashboard_url"] == f"/lead/{ids[0]}" and d["bid"] is None


def test_detail_prefers_the_fetched_posting(client, ctx, ids):
    ctx.assist.set_posting(ids[0], "Full page text", "fetched")
    d = client.get(f"/api/leads/{ids[0]}").json()
    assert d["body"] == "Full page text" and d["posting_origin"] == "fetched"


def test_detail_404(client, ids):
    assert client.get("/api/leads/99999").status_code == 404


def test_sources_lists_known_and_enabled(client, ctx):
    data = client.get("/api/sources").json()
    by_id = {s["id"]: s for s in data["sources"]}
    assert "freelancer" in by_id and by_id["freelancer"]["enabled"] is ("freelancer" in ctx.settings.enabled_sources)


def test_api_needs_the_same_access_as_the_dashboard(app):
    assert TestClient(app, client=OUTSIDE).get("/api/leads").status_code == 403
    assert TestClient(app, client=("127.0.0.1", 5000)).get("/api/leads").status_code == 403
