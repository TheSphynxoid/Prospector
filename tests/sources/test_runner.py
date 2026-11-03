from datetime import UTC, datetime, timedelta

import httpx
import respx

from prospector.models import RawLead
from prospector.sources.robots import robots_allowed
from prospector.sources.runner import run_source, should_run
from prospector.store.db import connect
from prospector.store.health import HealthRepo, SourceHealth

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


class FakeSource:
    id = "fake"
    interval_hours = 4

    def __init__(self, result=None, exc=None):
        self.result, self.exc = result or [], exc

    def fetch(self, http):
        if self.exc:
            raise self.exc
        return self.result


def lead(i, **kw):
    base = dict(source_id="fake", external_id=str(i), url=f"https://x/{i}", title=f"T{i}", body="b")
    base.update(kw)
    return RawLead(**base)


def run(src, health):
    with httpx.Client() as http:
        return run_source(src, http, health, NOW)


def test_exception_records_failure_and_pauses_after_three():
    h = HealthRepo(connect(":memory:"))
    for i in range(3):
        assert run(FakeSource(exc=RuntimeError("down")), h) == []
        assert h.get("fake").paused is (i == 2)
    assert h.get("fake").consecutive_failures == 3


def test_success_resets_and_unpauses():
    h = HealthRepo(connect(":memory:"))
    h.set_paused("fake", True)
    h.record_failure("fake", "x")
    out = run(FakeSource([lead(1), lead(2)]), h)
    st = h.get("fake")
    assert len(out) == 2 and st.consecutive_failures == 0 and not st.paused and not st.drift
    assert st.last_count == 2


def test_zero_leads_flags_drift():
    h = HealthRepo(connect(":memory:"))
    run(FakeSource([]), h)
    assert h.get("fake").drift


def test_half_missing_fields_flags_drift():
    h = HealthRepo(connect(":memory:"))
    run(FakeSource([lead(1), lead(2, title=""), lead(3, body=""), lead(4)]), h)
    assert not h.get("fake").drift
    run(FakeSource([lead(1), lead(2, title=""), lead(3, url="")]), h)
    assert h.get("fake").drift


def test_should_run_interval_and_never_run():
    src = FakeSource()
    assert should_run(SourceHealth("fake"), src, NOW)
    recent = SourceHealth("fake", last_run=(NOW - timedelta(hours=1)).isoformat())
    assert not should_run(recent, src, NOW)
    old = SourceHealth("fake", last_run=(NOW - timedelta(hours=5)).isoformat())
    assert should_run(old, src, NOW)


def test_should_run_paused_waits_24h():
    src = FakeSource()
    h = SourceHealth("fake", last_run=(NOW - timedelta(hours=5)).isoformat(), paused=True)
    assert not should_run(h, src, NOW)
    h.last_run = (NOW - timedelta(hours=25)).isoformat()
    assert should_run(h, src, NOW)


@respx.mock
def test_robots_disallow():
    respx.get("https://site.test/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /jobs\n"))
    with httpx.Client() as http:
        assert not robots_allowed("https://site.test/jobs/1", http, "prospector/0.1.0")
        assert robots_allowed("https://site.test/about", http, "prospector/0.1.0")


@respx.mock
def test_robots_fetch_failure_denies():
    respx.get("https://site.test/robots.txt").mock(return_value=httpx.Response(500))
    with httpx.Client() as http:
        assert not robots_allowed("https://site.test/jobs", http, "prospector/0.1.0")


@respx.mock
def test_robots_missing_allows():
    respx.get("https://site.test/robots.txt").mock(return_value=httpx.Response(404))
    with httpx.Client() as http:
        assert robots_allowed("https://site.test/jobs", http, "prospector/0.1.0")
