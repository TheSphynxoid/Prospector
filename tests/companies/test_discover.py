from datetime import UTC, datetime

import pytest

import prospector.companies.discover as d
from prospector.search.client import Hit, SearchResult
from tests.test_scheduler import make_ctx

NOW = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)  # 04:00 Tunis


@pytest.fixture
def ctx(tmp_path):
    c = make_ctx(tmp_path)
    c.profile.skills = {"go": 1, "c++": 1, "python": 0.6}
    c.settings.searxng_url = "http://h:8081"
    return c


def fake(results_by_call):
    calls = []

    def _search(ctx, query, engines="brave", max_results=20):
        calls.append((query, engines))
        i = len(calls) - 1
        return results_by_call(i) if callable(results_by_call) else results_by_call[i]
    return _search, calls


def ok(*urls):
    return SearchResult([Hit("t", u, "") for u in urls], False, None)


def test_queries_from_profile(ctx):
    q = d.queries(ctx.profile)
    assert len(q) == 16 and q[0] == "site:jobs.lever.co golang"
    assert q[1] == 'site:jobs.lever.co "c++"'
    assert "site:jobs.ashbyhq.com golang intern" in q and "site:boards.greenhouse.io golang junior" in q
    assert not any("python" in x for x in q)


def test_queries_other_skills(ctx):
    ctx.profile.skills = {"Rust": 2, "machine learning": 1, "go": 0.5}
    q = d.queries(ctx.profile)
    assert q[:4] == ["site:jobs.lever.co rust", 'site:jobs.lever.co "machine learning"',
                     "site:jobs.lever.co rust intern", "site:jobs.lever.co rust junior"]


def test_discover_adds_companies(ctx, monkeypatch):
    ctx.companies.add("lever", "old", "earlier")
    s, calls = fake(lambda i: ok("https://jobs.lever.co/acme/1", "https://jobs.lever.co/old/2", "https://x.com/a")
                    if i == 0 else ok("https://jobs.ashbyhq.com/ramp/abc?x=1"))
    monkeypatch.setattr(d, "search", s)
    st = d.discover(ctx, NOW, sleep=lambda _: None)
    assert st.searched == 16 and st.added == 2 and st.found >= 3 and not st.throttled and st.error is None
    by = {c.token: c for c in ctx.companies.list()}
    assert by["acme"].found_by == "site:jobs.lever.co golang"
    assert by["old"].found_by == "earlier"
    assert all(e == "brave" for _, e in calls)
    last = ctx.kv.get("discover_last")
    assert last["searched"] == 16 and last["added"] == 2 and last["at"].startswith("2026-11-05")


def test_discover_stops_when_throttled(ctx, monkeypatch):
    s, calls = fake(lambda i: SearchResult([], True, None) if i == 2 else ok("https://jobs.lever.co/a%d/1" % i))
    monkeypatch.setattr(d, "search", s)
    st = d.discover(ctx, NOW, sleep=lambda _: None)
    assert st.searched == 3 and st.throttled and st.added == 2 and len(calls) == 3
    until = datetime.fromisoformat(ctx.kv.get("discover_backoff_until"))
    assert until.astimezone(d.TZ).isoformat() == "2026-11-07T04:00:00+01:00"
    assert ctx.kv.get("discover_last")["throttled"] is True


@pytest.mark.parametrize("bad", [SearchResult([], False, None), SearchResult([], False, "HTTP 500 from h")])
def test_discover_stops_on_empty_or_error(ctx, monkeypatch, bad):
    s, calls = fake(lambda i: bad if i == 1 else ok("https://jobs.lever.co/a/1"))
    monkeypatch.setattr(d, "search", s)
    st = d.discover(ctx, NOW, sleep=lambda _: None)
    assert st.searched == 2 and len(calls) == 2 and ctx.kv.get("discover_backoff_until")
    assert st.error == bad.error


def test_discover_gap_applied(ctx, monkeypatch):
    s, _ = fake(lambda i: ok("https://jobs.lever.co/a/1"))
    monkeypatch.setattr(d, "search", s)
    slept = []
    st = d.discover(ctx, NOW, sleep=slept.append)
    assert slept == [20] * (st.searched - 1) and d.DISCOVER_GAP == 20


def test_scheduled_discover_skips(ctx, monkeypatch):
    ran = []
    monkeypatch.setattr(d, "discover", lambda c, now, **kw: ran.append(kw))
    ctx.settings.searxng_url = None
    d.scheduled_discover(ctx, NOW)
    assert ran == []
    ctx.settings.searxng_url = "http://h:8081"
    ctx.kv.set("discover_backoff_until", datetime(2026, 11, 6, 3, tzinfo=UTC).isoformat())
    d.scheduled_discover(ctx, NOW)
    assert ran == []
    d.scheduled_discover(ctx, datetime(2026, 11, 6, 3, tzinfo=UTC))
    assert len(ran) == 1


def test_manual_ignores_backoff_and_clears_it(ctx, monkeypatch):
    ctx.kv.set("discover_backoff_until", datetime(2026, 11, 7, 3, tzinfo=UTC).isoformat())
    s, calls = fake(lambda i: ok("https://jobs.lever.co/a/1"))
    monkeypatch.setattr(d, "search", s)
    d.discover(ctx, NOW, manual=True, sleep=lambda _: None)
    assert len(calls) == 16 and ctx.kv.get("discover_backoff_until") is None


def test_discover_without_search_does_nothing(ctx, monkeypatch):
    ctx.settings.searxng_url = None
    s, calls = fake(lambda i: ok())
    monkeypatch.setattr(d, "search", s)
    st = d.discover(ctx, NOW, manual=True, sleep=lambda _: None)
    assert calls == [] and st.error
