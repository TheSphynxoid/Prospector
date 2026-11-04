import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import TAILNET


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


def test_row_shows_reach_tag_and_bids(ctx, client, make_lead):
    ctx.profile.targets.levels = ["intern", "junior"]
    lid = ctx.leads.insert(make_lead(canonical_url="s", title="Senior Go Engineer"))
    ctx.leads.insert(make_lead(canonical_url="j", title="Junior Go Engineer"))
    ctx.signals.set_bids(lid, 52)
    page = client.get("/?tab=new").text
    assert page.count("Too senior") == 1 and "52 bids" in page
    assert "Too senior" in client.get(f"/lead/{lid}").text


def test_detail_shows_multipliers(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    ctx.scores.save_stage1(lid, 0.2, {"sim": 0.5, "reach": 0.35, "competition": 1.0, "final": 0.2})
    page = client.get(f"/lead/{lid}").text
    assert "×0.35" in page and "0.50" in page


def test_detail_renders_old_breakdown(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    ctx.scores.save_stage1(lid, 0.4, {k: 0.5 for k in ("sim", "keywords", "pay", "remote", "freshness",
                                                         "feedback", "final")})
    assert client.get(f"/lead/{lid}").status_code == 200
