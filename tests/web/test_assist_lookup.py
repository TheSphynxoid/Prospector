import pytest
from fastapi.testclient import TestClient

import prospector.assist.lookup as lk
from prospector.search.client import Hit, SearchResult

@pytest.fixture
def client(app):
    from tests.web.conftest import TAILNET
    return TestClient(app, client=TAILNET)


@pytest.fixture
def web_lid(ctx, make_lead, monkeypatch):
    monkeypatch.setattr("prospector.assist.fetch.fetch_posting",
                        lambda lead, *a, **k: __import__("prospector.assist.fetch", fromlist=["FetchResult"]).FetchResult(None, None, "no"))
    return ctx.leads.insert(make_lead())


def test_lookup_button_visibility(ctx, client, web_lid, make_lead):
    assert "Look up this company" not in client.get(f"/lead/{web_lid}").text
    ctx.settings.searxng_url = "http://h:8081"
    page = client.get(f"/lead/{web_lid}").text
    assert "Look up this company" in page and f'hx-post="/lead/{web_lid}/assist/lookup"' in page
    nocomp = ctx.leads.insert(make_lead(company=None, canonical_url="https://example.com/9"))
    assert "Look up this company" not in client.get(f"/lead/{nocomp}").text


def test_research_rendered_collapsed(ctx, client, web_lid, monkeypatch):
    from tests.assist.conftest import FakeLLM
    ctx.settings.searxng_url = "http://h:8081"
    ctx.assistant_llm = FakeLLM()
    ctx.assistant_llm.replies = ["Looks fine."]
    many = SearchResult([Hit(f"T{i}", f"https://x/{i}", "s") for i in range(10)], False, None)
    monkeypatch.setattr(lk, "search", lambda c, q, engines="brave", max_results=20: many)
    r = client.post(f"/lead/{web_lid}/assist/lookup")
    assert r.status_code == 200
    assert "<details" in r.text and "8 search results" in r.text and "Looks fine." in r.text
    assert lk.OPEN_R not in r.text and lk.CLOSE_R not in r.text
