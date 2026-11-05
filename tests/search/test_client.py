import httpx
import pytest
import respx

from prospector.search.client import Hit, search, search_ready

H = "http://h:8081"


class Ctx:
    def __init__(self, url=H):
        from types import SimpleNamespace
        self.settings = SimpleNamespace(searxng_url=url)
        self.http = httpx.Client()


@respx.mock
def test_search_maps_hits():
    respx.get(f"{H}/search").respond(json={"results": [
        {"title": f"T{i}", "url": f"https://x/{i}", "content": f"s{i}"} for i in range(5)],
        "unresponsive_engines": []})
    r = search(Ctx(), "q", max_results=3)
    assert r.results == [Hit("T0", "https://x/0", "s0"), Hit("T1", "https://x/1", "s1"), Hit("T2", "https://x/2", "s2")]
    assert r.throttled is False and r.error is None


@respx.mock
def test_search_throttled():
    respx.get(f"{H}/search").respond(json={"results": [], "unresponsive_engines": [["brave", "CAPTCHA"]]})
    assert search(Ctx(), "q").throttled is True


@respx.mock
@pytest.mark.parametrize("mock", ["500", "badjson", "conn"])
def test_search_errors_never_raise(mock):
    route = respx.get(f"{H}/search")
    if mock == "500":
        route.respond(500)
    elif mock == "badjson":
        route.respond(200, text="<html>nope")
    else:
        route.side_effect = httpx.ConnectError("down")
    r = search(Ctx(), "q")
    assert r.error and r.results == []


def test_search_without_url():
    r = search(Ctx(None), "q")
    assert r.error and r.results == [] and search_ready(Ctx(None)) is False
    assert search_ready(Ctx()) is True


@respx.mock
@pytest.mark.parametrize("base", ["http://h:8081/", "http://h:8081"])
def test_search_url_joins(base):
    route = respx.get(f"{H}/search").respond(json={"results": []})
    search(Ctx(base), "site:jobs.lever.co golang")
    req = route.calls.last.request
    assert str(req.url).startswith(f"{H}/search?")
    assert req.url.params["format"] == "json" and req.url.params["engines"] == "brave"
    assert req.url.params["q"] == "site:jobs.lever.co golang"
    search(Ctx(base), "x", engines=None)
    assert "engines" not in route.calls.last.request.url.params
