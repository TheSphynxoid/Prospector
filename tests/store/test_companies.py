from datetime import UTC, datetime, timedelta

from prospector.store.companies import CompanyRepo
from prospector.store.db import connect

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


def repo():
    return CompanyRepo(connect(":memory:"))


def test_add_dedupes():
    r = repo()
    assert r.add("lever", "acme", "q") is True
    assert r.add("lever", "acme", "other") is False
    assert r.add("ashby", "acme") is True
    [c] = r.list(state=None)[:1]
    assert c.state == "watching" and c.failures == 0 and c.last_checked is None


def test_due_respects_24h_and_limit():
    r = repo()
    r.add("lever", "fresh"); r.add("lever", "never"); r.add("lever", "muted"); r.add("lever", "old")
    by = {c.token: c for c in r.list()}
    r.conn.execute("UPDATE companies SET last_checked=? WHERE id=?", ((NOW - timedelta(hours=2)).isoformat(), by["fresh"].id))
    r.conn.execute("UPDATE companies SET last_checked=? WHERE id=?", ((NOW - timedelta(hours=30)).isoformat(), by["old"].id))
    r.set_state(by["muted"].id, "muted")
    assert [c.token for c in r.due(NOW, 1)] == ["never"]
    assert [c.token for c in r.due(NOW, 40)] == ["never", "old"]


def test_errors_pause_and_watching_resets():
    r = repo()
    r.add("lever", "acme")
    cid = r.list()[0].id
    r.record_error(cid, "HTTP 404"); r.record_error(cid, "HTTP 404")
    assert r.get(cid).state == "watching" and r.get(cid).failures == 2
    r.record_ok(cid, 3, "Acme")
    assert r.get(cid).failures == 0 and r.get(cid).name == "Acme" and r.get(cid).last_count == 3
    for _ in range(3):
        r.record_error(cid, "HTTP 404")
    c = r.get(cid)
    assert c.state == "paused" and c.last_error == "HTTP 404" and c.last_checked is not None
    r.set_state(cid, "watching")
    assert r.get(cid).state == "watching" and r.get(cid).failures == 0


def test_list_order_and_counts():
    r = repo()
    for t in ("a", "b", "c", "d"):
        r.add("lever", t)
    ids = {c.token: c.id for c in r.list()}
    r.record_ok(ids["a"], 1, "Zed"); r.record_ok(ids["b"], 5, "Bee"); r.set_state(ids["c"], "muted")
    assert [c.token for c in r.list()] == ["b", "a", "d", "c"]
    assert [c.token for c in r.list("muted")] == ["c"]
    assert r.counts() == {"watching": 3, "muted": 1, "paused": 0}
    assert r.get(9999) is None
