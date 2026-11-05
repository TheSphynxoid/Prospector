from datetime import UTC, datetime, timedelta

import pytest

import prospector.companies.discover as disc
from prospector.search.client import Hit, SearchResult
from tests.web.test_settings_page import env, form_of, saved, setup  # noqa: F401  (fixtures)


@pytest.fixture
def client(setup):
    return setup[0]


def test_companies_page_lists_and_filters(client, ctx):
    ctx.companies.add("lever", "sensor-tower", "site:jobs.lever.co golang")
    ctx.companies.add("ashby", "ramp")
    ctx.companies.add("greenhouse", "muted-co")
    ids = {c.token: c.id for c in ctx.companies.list()}
    ctx.companies.record_ok(ids["ramp"], 4, "Ramp")
    ctx.companies.set_state(ids["muted-co"], "muted")
    page = client.get("/settings/companies").text
    assert "Sensor Tower" in page and "Ramp" in page and "Muted Co" in page
    assert "site:jobs.lever.co golang" in page
    assert page.index("Ramp") < page.index("Sensor Tower") < page.index("Muted Co")
    muted = client.get("/settings/companies?state=muted").text
    assert "Muted Co" in muted and "Sensor Tower" not in muted
    assert 'aria-current="page"' in muted


def test_add_company_by_link(client, ctx):
    r = client.post("/settings/companies/add", data={"url": "https://jobs.ashbyhq.com/sensor-tower/b6505a02"})
    assert r.status_code == 200 and "Added Sensor Tower (Ashby)" in r.text
    assert ctx.companies.list()[0].found_by == "added by you"
    r = client.post("/settings/companies/add", data={"url": "https://jobs.ashbyhq.com/sensor-tower"})
    assert "Already watched" in r.text
    r = client.post("/settings/companies/add", data={"url": "https://example.com/careers"})
    assert r.status_code == 400 and "Not a Greenhouse, Lever or Ashby link" in r.text
    assert len(ctx.companies.list()) == 1


def test_mute_unmute_resume(client, ctx):
    ctx.companies.add("lever", "acme")
    cid = ctx.companies.list()[0].id
    assert ">Mute<" in client.get("/settings/companies").text
    page = client.post(f"/settings/companies/{cid}/state", data={"state": "muted"}).text
    assert ctx.companies.get(cid).state == "muted" and ">Unmute<" in page
    client.post(f"/settings/companies/{cid}/state", data={"state": "watching"})
    assert ctx.companies.get(cid).state == "watching"
    for _ in range(3):
        ctx.companies.record_error(cid, "HTTP 404 from api.lever.co")
    page = client.get("/settings/companies").text
    assert ">Resume<" in page and "HTTP 404 from api.lever.co" in page
    client.post(f"/settings/companies/{cid}/state", data={"state": "watching"})
    c = ctx.companies.get(cid)
    assert c.state == "watching" and c.failures == 0
    assert client.post(f"/settings/companies/{cid}/state", data={"state": "bogus"}).status_code == 400
    assert client.post("/settings/companies/9999/state", data={"state": "muted"}).status_code == 404


def test_discover_now(client, ctx, monkeypatch):
    r = client.post("/settings/companies/discover")
    assert r.status_code == 400 and "Set up web search in Settings → Connections" in r.text
    assert "Set up web search" in client.get("/settings/companies").text
    ctx.settings.searxng_url = "http://h:8081"
    ctx.kv.set("discover_backoff_until", (datetime.now(UTC) + timedelta(days=1)).isoformat())
    monkeypatch.setattr(disc, "search", lambda c, q, engines="brave", max_results=20:
                        SearchResult([Hit("t", "https://jobs.lever.co/acme/1", "")], False, None))
    monkeypatch.setattr(disc, "DISCOVER_GAP", 0)
    monkeypatch.setattr(disc.time, "sleep", lambda s: None)
    r = client.post("/settings/companies/discover")
    assert r.status_code == 200 and "Discovery started" in r.text
    assert [c.token for c in ctx.companies.list()] == ["acme"]
    assert r.history and r.history[0].status_code == 303  # a refresh doesn't start another run
    monkeypatch.setattr("prospector.web.settings.companies.is_running", lambda: True)
    r = client.post("/settings/companies/discover")
    assert "Discovery is already running" in r.text and "disabled" in r.text


def test_last_discovery_and_backoff_shown(client, ctx):
    ctx.kv.set("discover_last", {"at": "2026-11-05T03:00:00+00:00", "searched": 16, "found": 9, "added": 3,
                                 "throttled": False, "error": None, "manual": False})
    page = client.get("/settings/companies").text
    assert "searched 16, added 3" in page and "throttled" not in page
    ctx.kv.set("discover_backoff_until", (datetime.now(UTC) + timedelta(days=1)).isoformat())
    assert "search throttled, next run" in client.get("/settings/companies").text


def test_sources_page_links_companies(client, ctx):
    ctx.companies.add("lever", "acme")
    page = client.get("/settings/sources").text
    assert 'href="/settings/companies"' in page and "Companies: 1 watching" in page
    assert 'href="/settings/companies"' in client.get("/settings").text
